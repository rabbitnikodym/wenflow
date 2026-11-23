"""Builds each day's ~30 minute lesson from the curriculum, the decks and freshly generated material."""
from __future__ import annotations

import json
import logging
import random
import re
import threading
from datetime import date, datetime, timedelta

from . import content_store, curriculum, db, decks, llm, srs, text, zhuyin_course
from .zhuyin import pinyin_to_zhuyin

log = logging.getLogger("wenflow.lessons")
_build_lock = threading.Lock()


# ----------------------------------------------------------------------------------------------
# Lookup / lifecycle
# ----------------------------------------------------------------------------------------------

def _row(day: int) -> dict | None:
    r = db.q1("SELECT * FROM lessons WHERE day=?", (day,))
    if r:
        r["plan"] = json.loads(r["plan"] or "{}")
        r["progress"] = json.loads(r["progress"] or "{}")
    return r


def current_day() -> int:
    r = db.q1("SELECT max(day) d FROM lessons")
    return (r and r["d"]) or 0


def today() -> dict:
    """Today's lesson. An untouched earlier lesson is carried forward rather than skipped."""
    with _build_lock:
        r = db.q1("SELECT day FROM lessons WHERE date=? ORDER BY day DESC LIMIT 1", (db.today(),))
        if r:
            return hydrate(_row(r["day"]))
        last = current_day()
        if last:
            prev = _row(last)
            if prev["status"] != "done" and not any(v.get("done") for v in prev["progress"].values()):
                db.ex("UPDATE lessons SET date=? WHERE day=?", (db.today(), last))
                return hydrate(_row(last))
        return hydrate(_create(last + 1))


def start_next() -> dict:
    """Begin the next lesson early (after finishing today's)."""
    with _build_lock:
        return hydrate(_create(current_day() + 1))


def get(day: int) -> dict | None:
    r = _row(day)
    return hydrate(r) if r else None


def _create(day: int) -> dict:
    if not db.get_setting("start_date"):
        db.set_setting("start_date", db.today())
    plan = build(day)
    db.ex("INSERT OR REPLACE INTO lessons(day,date,plan,progress,status,generated_at) VALUES(?,?,?,?,?,?)",
          (day, db.today(), json.dumps(plan, ensure_ascii=False), "{}", "new", db.now()))
    return _row(day)


# ----------------------------------------------------------------------------------------------
# Building
# ----------------------------------------------------------------------------------------------

def _pick_tw(n: int, prefer: list[str], phase: int) -> list[dict]:
    """Next Taiwan words, favouring this week's categories among the nearest upcoming items."""
    if n <= 0:
        return []
    window = decks.next_words("tw", 60)
    pref = {p.lower() for p in prefer}
    alias = {"transit": "transport", "discourse": "expression", "social": "relationship", "home": "housing",
             "government": "admin", "money": "shopping", "travel": "transport", "culture": "food-culture"}
    pref |= {alias[p] for p in list(pref) if p in alias}
    chosen = [w for w in window if (w.get("category") or "").lower() in pref][:n]
    for w in window:
        if len(chosen) >= n:
            break
        if w not in chosen:
            chosen.append(w)
    return chosen


def _tomorrow() -> datetime:
    return datetime.combine(date.today() + timedelta(days=1), datetime.min.time()) + timedelta(hours=3)


def build(day: int) -> dict:
    pos = curriculum.position(day)
    info, phase = pos["info"], pos["phase"]
    tpl = curriculum.template(day)

    # Zhuyin first. The day's unit is the first one not finished yet, so a unit done ahead of time
    # in the Zhuyin tab is not repeated and one that was left out is not skipped. If the course is
    # still running after phase 0, it takes over the keyboard warm-up slot.
    zunit = zhuyin_course.next_unit()
    if zunit and not any(t == "zhuyin" for t, _ in tpl):
        tpl = [("zhuyin", max(m, 6)) if i == 0 and t in curriculum.LEAD_BLOCKS else (t, m) for i, (t, m) in enumerate(tpl)]
    has_unit = bool(zunit) and any(t == "zhuyin" for t, _ in tpl)
    # What the learner can do once that first block is done; the rest of the day stays inside it.
    level = None if not zunit else zunit if has_unit else zunit - 1
    tpl = curriculum.fit_to_zhuyin(tpl, level)
    types = [t for t, _ in tpl]
    rng = random.Random(day * 104729)
    had_cards = bool(db.q1("SELECT count(*) n FROM cards")["n"])

    n_tw, n_h6, n_book = curriculum.VOCAB_MIX[phase]
    words = _pick_tw(n_tw, info.get("taiwan_categories", []), phase) + decks.next_words("hsk6", n_h6) + decks.next_words("book", n_book)

    grammar = decks.next_grammar(phase) if "grammar" in types else None
    pron = decks.next_pron(4) if "pron" in types else []
    bridge = None
    if "chars" in types:
        ptr = db.get_setting("bridge_ptr", 0)
        bridge = decks.bridge_unit_payload(ptr)
        if bridge:
            db.set_setting("bridge_ptr", ptr + 1)
    from . import library

    book_chunk = library.next_book_chunk(curriculum.BOOK_CHUNK[phase]) if "book" in types else None
    news = library.pick_news(phase) if "news" in types else None
    need_reading = "reading" in types or ("book" in types and not book_chunk) or ("news" in types and not news)
    story_mode = "book" in types and not book_chunk

    gen = generate(pos, words, grammar, need_reading, story_mode, "writing" in types)

    # Fill in examples the model wrote for words that had none.
    for w in words:
        ex = (gen.get("examples") or {}).get(w["trad"])
        if not w.get("example") and isinstance(ex, dict) and ex.get("zh"):
            w["example"] = {"zh": text.ensure_traditional(ex["zh"]), "en": ex.get("en", "")}

    due = _tomorrow()
    for w in words:
        data = {k: w.get(k) for k in ("trad", "simp", "pinyin", "zhuyin", "en", "deck", "example", "note", "mainland",
                                       "category", "register", "mainland_pinyin") if w.get(k)}
        srs.add_card("word", w["trad"], data, source=w.get("deck", ""), due=due)
    if bridge:
        for c in bridge["cards"]:
            data = {k: c.get(k) for k in ("t", "s", "words", "tip", "pinyin", "zhuyin", "en", "word_info") if c.get(k)}
            srs.add_card("char", c["t"], data, source="bridge", due=due)
    for p in pron:
        srs.add_card("pron", p["trad"], p, source="pron", due=due)

    sentences = gen.get("sentences") or []
    scen_ids = info.get("scenario_ids") or [s["id"] for s in content_store.scenarios()[:2]]
    blocks = []
    for i, (btype, minutes) in enumerate(tpl):
        en, zh = curriculum.BLOCK_TITLES[btype]
        b: dict = {"id": f"b{i + 1}", "type": btype, "title": en, "title_zh": zh, "minutes": minutes, "payload": {}}
        p = b["payload"]
        if btype == "review":
            if not had_cards:
                continue  # the very first lesson: nothing has been learned yet, so nothing is due
            p["limit"] = 30 if minutes <= 4 else 40
        elif btype == "zhuyin":
            if zunit:
                p["unit"] = zunit
            else:
                b.update(type="typing", title="Typing", title_zh="打字")
                p["sentences"] = [s["zh"] for s in sentences[:4]] or None
                p["stock"] = 5
        elif btype == "typing":
            p["sentences"] = [s["zh"] for s in sentences[:4]] or None
            p["stock"] = 4
        elif btype == "dictation":
            p["sentences"] = [s for s in sentences[2:6]] or [s for s in sentences[:4]]
        elif btype == "chars":
            if bridge:
                p.update(bridge)
            else:
                # The bridge is finished: write earlier words from memory instead.
                b.update(title="Handwriting", title_zh="手寫")
                p["recall"] = True
        elif btype == "vocab":
            p["words"] = words
        elif btype == "grammar":
            if grammar:
                p["point"] = grammar
            else:
                continue
        elif btype == "pron":
            if pron:
                p["items"] = pron
            else:
                continue
        elif btype in ("reading", "news", "book"):
            if btype == "book" and book_chunk:
                p.update(book_chunk)
            elif btype == "news" and news:
                p.update(news)
            elif gen.get("reading"):
                p.update(gen["reading"])
                if btype == "book":
                    p["no_book"] = True
                    notes = content_store.book_pack().get("culture_notes") or []
                    if notes:
                        p["culture_note"] = notes[(day // 7) % len(notes)]
                if btype == "news":
                    b.update(title="Reading", title_zh="閱讀")
            else:
                continue
        elif btype == "video":
            p["watch_minutes"] = minutes
        elif btype == "shadow":
            p["sentences"] = sentences[:4] if sentences else [{"zh": z, "en": e} for z, e in rng.sample(zhuyin_course.BASE_SENTENCES, 4)]
            p["focus"] = info.get("speaking_focus", "")
        elif btype == "conversation":
            idx = 0 if pos["dow"] in (3, 6) else 1
            p["scenario_id"] = scen_ids[idx % len(scen_ids)]
            p["turns"] = 5 if minutes <= 7 else 7
            p["twist"] = phase >= 3
        elif btype == "writing":
            wp = gen.get("writing") or {}
            p["prompt_zh"] = wp.get("prompt_zh") or "用今天學到的詞，寫兩三句話描述你的一天。"
            p["prompt_en"] = wp.get("prompt_en") or "Using today's words, write two or three sentences about your day."
            p["must_use"] = [w["trad"] for w in words[:3]]
            p["min_chars"] = {0: 20, 1: 40, 2: 60, 3: 90, 4: 120}[phase] if minutes <= 4 else {0: 30, 1: 80, 2: 120, 3: 180, 4: 220}[phase]
            p["task"] = info.get("writing_task", "")
        elif btype == "checkpoint":
            p["items"] = checkpoint_items(rng, None if level is None else zhuyin_course.symbols_through(level))
            p["milestone"] = info.get("milestone")
            if not p["items"]:
                continue
        blocks.append(b)

    return {
        "day": day, "week": pos["week"], "dow": pos["dow"], "phase": phase,
        "week_title": info.get("title", ""), "week_title_zh": info.get("title_zh", ""), "theme": info.get("theme", ""),
        "goals": info.get("goals", []), "blocks": blocks, "minutes": sum(b["minutes"] for b in blocks),
        "generated": bool(gen.get("_llm")),
    }


def generate(pos: dict, words: list[dict], grammar: dict | None, need_reading: bool, story_mode: bool,
             need_writing: bool) -> dict:
    """One model call for the day's reading passage, practice sentences, missing examples and writing prompt."""
    info, phase = pos["info"], pos["phase"]
    lo, hi = curriculum.READING_LEN[phase]
    need_examples = [w["trad"] for w in words if not w.get("example")]
    word_list = "、".join(f"{w['trad']}（{(w.get('en') or '')[:40]}）" for w in words) or "（無）"
    level = {0: "HSK 4（短句、常用詞）", 1: "HSK 5", 2: "HSK 5–6", 3: "HSK 6", 4: "HSK 6 以上"}[phase]
    genre = "原創的校園青春短篇故事（1990年代台灣中部的高中，第一人稱，口語、幽默）。不可引用或改寫任何現有小說的內容" if story_mode \
        else (info.get("reading_genre") or "生活短文")
    spec = {
        "sentences": "6 個自然的台灣口語句子（每句 8–18 個字），和本週主題有關，盡量用到今日生詞。格式 [{\"zh\":\"…\",\"en\":\"…\"}]",
    }
    if need_reading:
        spec["reading"] = (
            f"一篇 {lo}–{hi} 字的短文，文體：{genre}。自然地用到大部分今日生詞。分成 2–4 段，段落之間用 \\n\\n。"
            "格式 {\"title\":\"…\",\"text\":\"…\",\"questions\":[{\"q\":\"中文問題\",\"options\":[\"…\",\"…\",\"…\",\"…\"],"
            "\"answer\":0,\"explain\":\"one-sentence English explanation\"}]}，共 3 題理解題，answer 是正確選項的索引。"
        )
    if need_examples:
        spec["examples"] = "為這些詞各寫一個 8–20 字的自然例句：" + "、".join(need_examples) + \
            "。格式 {\"詞\":{\"zh\":\"…\",\"en\":\"…\"}}"
    if need_writing:
        spec["writing"] = (
            "一個寫作題目，配合本週任務「" + (info.get("writing_task") or "描述日常生活") + "」但今天只需要寫幾句話。"
            "格式 {\"prompt_zh\":\"…\",\"prompt_en\":\"…\"}"
        )
    system = (
        llm.TW_STYLE + "你在為一位學習者編寫每日教材。文字裡不要加注音、拼音或括號標音（系統會自動標註）。學習者的程度大約是 " + level +
        "，原本學的是中國大陸的普通話和簡體字，現在要學台灣華語、繁體字和注音。"
        "內容要有台灣的生活感（地名、食物、習慣都用台灣的），不要像教科書。英文翻譯要自然。"
    )
    user = json.dumps({
        "week": pos["week"], "theme": info.get("title_zh") or info.get("title"), "theme_detail": info.get("theme"),
        "domains": info.get("vocab_domains"), "today_words": word_list,
        "grammar_point": (grammar or {}).get("pattern"), "produce": spec,
    }, ensure_ascii=False)
    try:
        if not llm.available():
            raise RuntimeError("no API key")
        out = llm.chat_json(system, user)
        out = _clean(out)
        out["_llm"] = True
        return out
    except Exception as e:  # noqa: BLE001 - lessons must still work offline
        log.warning("lesson generation failed, using fallback: %s", e)
        return _fallback(words, need_reading)


_INLINE_RUBY = re.compile(r"[（(][\sㄅ-ㄩˊˇˋ˙ˉa-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü]+[)）]")


def _clean(out: dict) -> dict:
    """Normalise model output: Traditional characters, no inline readings, well-formed questions."""
    out = json.loads(_INLINE_RUBY.sub("", json.dumps(out, ensure_ascii=False)))
    res: dict = {}
    sents = []
    for s in out.get("sentences") or []:
        if isinstance(s, dict) and s.get("zh"):
            sents.append({"zh": text.ensure_traditional(str(s["zh"]).strip()), "en": str(s.get("en", "")).strip()})
    res["sentences"] = sents
    r = out.get("reading")
    if isinstance(r, dict) and r.get("text"):
        qs = []
        for q in r.get("questions") or []:
            opts = q.get("options") or []
            ans = q.get("answer", 0)
            if isinstance(ans, str) and ans.strip()[:1].upper() in "ABCD":
                ans = "ABCD".index(ans.strip()[:1].upper())
            if len(opts) >= 2 and isinstance(ans, int) and 0 <= ans < len(opts):
                qs.append({"q": text.ensure_traditional(str(q.get("q", ""))),
                           "options": [text.ensure_traditional(str(o)) for o in opts], "answer": ans,
                           "explain": str(q.get("explain", ""))})
        res["reading"] = {"title": text.ensure_traditional(str(r.get("title", ""))),
                          "text": text.ensure_traditional(str(r["text"]).strip()), "questions": qs}
    if isinstance(out.get("examples"), dict):
        res["examples"] = out["examples"]
    if isinstance(out.get("writing"), dict):
        res["writing"] = {"prompt_zh": text.ensure_traditional(str(out["writing"].get("prompt_zh", ""))),
                          "prompt_en": str(out["writing"].get("prompt_en", ""))}
    return res


def _fallback(words: list[dict], need_reading: bool) -> dict:
    sents = [w["example"] for w in words if w.get("example")]
    sents += [{"zh": z, "en": e} for z, e in zhuyin_course.BASE_SENTENCES]
    out: dict = {"sentences": sents[:6]}
    if need_reading:
        body = "".join(s["zh"] for s in sents[:8])
        out["reading"] = {"title": "今日例句", "text": body, "questions": []}
    return out


# ----------------------------------------------------------------------------------------------
# Weekly checkpoint
# ----------------------------------------------------------------------------------------------

_SWAPS = [("ㄣ", "ㄥ"), ("ㄓ", "ㄗ"), ("ㄔ", "ㄘ"), ("ㄕ", "ㄙ"), ("ㄢ", "ㄤ"), ("ㄋ", "ㄌ"), ("ㄖ", "ㄌ"), ("ㄈ", "ㄏ"),
          ("ㄟ", "ㄝ"), ("ㄡ", "ㄛ"), ("ㄩ", "ㄧ")]


def zhuyin_distractors(zy: str, rng: random.Random, n: int = 3) -> list[str]:
    """Near-miss spellings: one tone changed or one commonly confused symbol swapped."""
    out: set[str] = set()
    syls = zy.split()
    marks = ["", "ˊ", "ˇ", "ˋ"]
    for _ in range(40):
        if len(out) >= n:
            break
        i = rng.randrange(len(syls))
        s = syls[i]
        if rng.random() < 0.5:
            body = s.strip("ˊˇˋ˙")
            new = body + rng.choice(marks)
        else:
            a, b = rng.choice(_SWAPS)
            new = s.replace(a, b) if a in s else s.replace(b, a) if b in s else s
        if new != s:
            cand = " ".join(syls[:i] + [new] + syls[i + 1:])
            if cand != zy:
                out.add(cand)
    return list(out)[:n]


def checkpoint_items(rng: random.Random, known: str | None = None) -> list[dict]:
    """Questions on the last nine days. `known` limits zhuyin questions to symbols taught so far."""
    since = (datetime.now() - timedelta(days=9)).isoformat(timespec="seconds")
    cards = db.q("SELECT kind, key, data FROM cards WHERE created_at>=? ORDER BY id DESC LIMIT 200", (since,))
    for c in cards:
        c["data"] = json.loads(c["data"])
    chars = [c for c in cards if c["kind"] == "char"]
    words = [c for c in cards if c["kind"] == "word"]
    items: list[dict] = []
    for c in rng.sample(chars, min(4, len(chars))):
        d = c["data"]
        items.append({"kind": "write", "char": d["t"], "simp": d.get("s", ""), "pinyin": d.get("pinyin", ""),
                      "zhuyin": d.get("zhuyin", ""), "en": d.get("en", ""), "word": (d.get("words") or [""])[0]})
    for c in rng.sample(words, min(3, len(words))):
        d = c["data"]
        zy = d.get("zhuyin", "")
        if known is not None and not set(re.sub(r"[ ˊˇˋ˙]", "", zy)) <= set(known):
            continue
        wrong = zhuyin_distractors(zy, rng) if zy else []
        if len(wrong) < 2:
            continue
        opts = [zy] + wrong
        rng.shuffle(opts)
        items.append({"kind": "mcq", "prompt": d["trad"], "sub": "Which zhuyin is right?", "options": opts,
                      "answer": opts.index(zy), "explain": f"{d.get('pinyin', '')} — {d.get('en', '')}"})
    tw = [c for c in words if c["data"].get("mainland")]
    pool = [c["data"]["trad"] for c in words]
    for c in rng.sample(tw, min(3, len(tw))):
        d = c["data"]
        others = [w for w in pool if w != d["trad"]]
        if len(others) < 3:
            continue
        opts = [d["trad"]] + rng.sample(others, 3)
        rng.shuffle(opts)
        items.append({"kind": "mcq", "prompt": d["mainland"], "sub": "What do people say in Taiwan?", "options": opts,
                      "answer": opts.index(d["trad"]), "explain": d.get("note") or d.get("en", "")})
    for c in rng.sample(words, min(2, len(words))):
        d = c["data"]
        others = [w["data"].get("en", "") for w in words if w["key"] != c["key"] and w["data"].get("en")]
        if len(others) < 3 or not d.get("en"):
            continue
        opts = [d["en"]] + rng.sample(others, 3)
        rng.shuffle(opts)
        items.append({"kind": "mcq", "prompt": d["trad"], "sub": "Meaning?", "options": opts, "answer": opts.index(d["en"]),
                      "explain": d.get("pinyin", "")})
    return items


# ----------------------------------------------------------------------------------------------
# Serving / progress
# ----------------------------------------------------------------------------------------------

def _sync_zhuyin(row: dict) -> None:
    """Bring a stored plan in line with the zhuyin course as it stands now.

    The zhuyin block leads (plans made before that rule are reordered), and a unit that has since
    been finished from the Zhuyin tab is replaced by the next one."""
    plan, prog = row["plan"], row["progress"]
    blocks = plan.get("blocks") or []
    changed = False
    lead = next((i for i, b in enumerate(blocks) if b["type"] in curriculum.LEAD_BLOCKS), None)
    if lead and all(b["type"] == "review" for b in blocks[:lead]):
        blocks.insert(0, blocks.pop(lead))
        changed = True
    done = set(db.get_setting("zhuyin_done", []) or [])
    for b in blocks:
        if b["type"] == "zhuyin" and not prog.get(b["id"], {}).get("done") and b["payload"].get("unit") in done:
            nxt = zhuyin_course.next_unit()
            if nxt:
                b["payload"]["unit"] = nxt
            else:
                b.update(type="typing", title="Typing", title_zh="打字", payload={"sentences": None, "stock": 5})
            changed = True
    if changed:
        db.ex("UPDATE lessons SET plan=? WHERE day=?", (json.dumps(plan, ensure_ascii=False), plan["day"]))


def hydrate(row: dict) -> dict:
    """Attach live annotation (zhuyin/pinyin tokens) and progress to a stored plan."""
    _sync_zhuyin(row)
    plan = row["plan"]
    prog = row["progress"]
    for b in plan.get("blocks", []):
        p = b["payload"]
        b["done"] = bool(prog.get(b["id"], {}).get("done"))
        b["result"] = prog.get(b["id"], {})
        t = b["type"]
        if t in ("reading", "news", "book") and p.get("text"):
            p["paragraphs"] = [text.annotate(par) for par in p["text"].split("\n") if par.strip()]
        if t in ("shadow", "dictation"):
            for s in p.get("sentences") or []:
                s["tokens"] = text.annotate(s["zh"], with_gloss=False)
        if t == "typing":
            items = [zhuyin_course.sentence_item(z) for z in (p.get("sentences") or [])]
            if len(items) < 4:
                items += zhuyin_course.typing_sentences(p.get("stock", 4) - len(items) + 1, random.Random(plan["day"]))
            p["items"] = items
        if t == "dictation":
            for s in p.get("sentences") or []:
                s["item"] = zhuyin_course.sentence_item(s["zh"], s.get("en", ""))
        if t == "grammar" and p.get("point"):
            for ex in p["point"].get("examples", []):
                ex["tokens"] = text.annotate(ex["zh"], with_gloss=False)
        if t == "vocab":
            for w in p.get("words", []):
                if w.get("example", {}).get("zh"):
                    w["example"]["tokens"] = text.annotate(w["example"]["zh"], with_gloss=False)
        if t == "pron":
            for it in p.get("items", []):
                it.setdefault("tw_zhuyin", " ".join(pinyin_to_zhuyin(s) for s in it.get("tw", "").split()))
                if it.get("example", {}).get("zh"):
                    it["example"]["tokens"] = text.annotate(it["example"]["zh"], with_gloss=False)
        if t == "conversation":
            sc = content_store.scenario(p.get("scenario_id", ""))
            if sc:
                p["scenario"] = {k: sc.get(k) for k in ("id", "title", "title_zh", "setting", "goals", "level")}
    done = sum(1 for b in plan.get("blocks", []) if b["done"])
    plan.update({"date": row["date"], "status": row["status"], "done_blocks": done,
                 "done_minutes": sum(b["minutes"] for b in plan.get("blocks", []) if b["done"])})
    return plan


def complete_block(day: int, block_id: str, data: dict | None = None) -> dict:
    row = _row(day)
    if not row:
        raise KeyError(day)
    data = data or {}
    block = next((b for b in row["plan"]["blocks"] if b["id"] == block_id), None)
    if not block:
        raise KeyError(block_id)
    prog = row["progress"]
    first = not prog.get(block_id, {}).get("done")
    prog[block_id] = {**prog.get(block_id, {}), **data, "done": True, "at": db.now()}
    t, p = block["type"], block["payload"]
    if first:
        if t == "zhuyin" and p.get("unit"):
            zhuyin_course.mark_done(p["unit"])
        if t == "grammar" and p.get("point"):
            decks.mark_grammar(p["point"]["id"])
            for pr in p["point"].get("practice", [])[:2]:
                if pr.get("zh") and pr.get("en"):
                    decks.add_sentence_card(pr["zh"], pr["en"], source="grammar")
        if t in ("typing", "dictation") and data.get("cpm") is not None:
            db.ex("INSERT INTO typing_stats(ts,mode,chars,seconds,accuracy) VALUES(?,?,?,?,?)",
                  (db.now(), t, int(data.get("chars", 0)), float(data.get("seconds", 0)), float(data.get("accuracy", 0))))
        if t == "book" and p.get("chapter_id") is not None and not p.get("no_book"):
            from . import library

            library.mark_read(p["chapter_id"], p.get("end", 0))
        db.log_activity(t, int(data.get("seconds") or block["minutes"] * 60), {"day": day})
    all_done = all(prog.get(b["id"], {}).get("done") for b in row["plan"]["blocks"])
    status = "done" if all_done else "started"
    db.ex("UPDATE lessons SET progress=?, status=? WHERE day=?", (json.dumps(prog, ensure_ascii=False), status, day))
    return hydrate(_row(day))


def streak() -> int:
    days = {r["day"] for r in db.q("SELECT DISTINCT day FROM activity")}
    n = 0
    d = date.today()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


def summary() -> dict:
    day = current_day()
    pos = curriculum.position(max(day, 1))
    mins = db.q1("SELECT coalesce(sum(seconds),0) s FROM activity WHERE day=?", (db.today(),))["s"] // 60
    done = db.q1("SELECT count(*) n FROM lessons WHERE status='done'")["n"]
    start = db.get_setting("start_date")
    elapsed = (date.today() - date.fromisoformat(start)).days + 1 if start else 0
    return {
        "day": day, "week": pos["week"], "phase": pos["phase"], "phase_info": curriculum.PHASES[pos["phase"]],
        "week_title": pos["info"].get("title", ""), "week_title_zh": pos["info"].get("title_zh", ""),
        "streak": streak(), "minutes_today": int(mins), "lessons_done": done, "start_date": start,
        "days_elapsed": elapsed, "on_pace": day >= elapsed if elapsed else True,
    }
