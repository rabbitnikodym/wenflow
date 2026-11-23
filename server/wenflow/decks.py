"""Study decks: what there is to learn and what comes next.

Decks
  char   Simplified -> Traditional bridge, grouped into small daily units
  tw     Taiwan-specific vocabulary (curated + CC-CEDICT "(Tw)" entries)
  hsk6   HSK 6 vocabulary in Traditional, by frequency
  book   vocabulary for the novel (companion pack + words mined from an imported text)
  pron   words pronounced differently in Taiwan
  grammar

An item counts as introduced once a card with its (kind, key) exists.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from . import content_store, db, dictionary, srs, text
from .config import RAW_DIR
from .zhuyin import pinyin_num_to_marks, pinyin_to_zhuyin

HAN = text.HAN_RE


# ----------------------------------------------------------------------------------------------
# word helpers
# ----------------------------------------------------------------------------------------------

def _toneless(py: str) -> str:
    return "".join(text.split_tone(x)[0] for x in py.split())


def describe(word: str, base: dict | None = None) -> dict:
    """Full display record for a word: Taiwan reading, zhuyin, simplified form, gloss.
    A hand-checked reading in `base` wins over the computed one."""
    base = base or {}
    out: dict = {"trad": word}
    all_han = bool(word) and all(HAN.match(c) for c in word)
    curated = (base.get("pinyin") or "").strip()
    if curated and (not all_han or len(curated.split()) == len(word)):
        out["pinyin"] = curated
        out["zhuyin"] = " ".join(pinyin_to_zhuyin(s) for s in curated.split())
    elif all_han:
        pys = [p for p in text._word_reading(word) if p != "?"]
        out["pinyin"] = " ".join(pinyin_num_to_marks(p) for p in pys)
        out["zhuyin"] = " ".join(pinyin_to_zhuyin(p) for p in pys)
    else:
        chars = [c for t in text.annotate(word, with_gloss=False) if t["han"] for c in t["chars"]]
        out["pinyin"] = " ".join(c["py"] for c in chars)
        out["zhuyin"] = " ".join(c["zy"] for c in chars)
    simp = text._t2s.convert(word)
    out["simp"] = simp if simp != word else ""
    hits = dictionary.lookup(word)
    if hits:
        # Prefer the dictionary sense that matches the reading we show (說 shuō, not shuì).
        want = _toneless(out.get("pinyin", ""))
        same = [h for h in hits if _toneless(h["pinyin"]) == want and not h.get("proper")] or \
               [h for h in hits if _toneless(h["pinyin"]) == want] or hits
        # Several senses share the reading (東西 'thing' / 'east and west'): take the everyday one.
        hit = max(same, key=lambda h: (h["hsk"] is not None, len(h["defs"])))
        defs = [d for d in hit["defs"] if not d.startswith(("variant of", "old variant", "CL:", "surname "))]
        out["en"] = "; ".join((defs or hit["defs"])[:3])
        out["hsk"] = next((h["hsk"] for h in hits if h["hsk"]), None)
        if hit.get("mainland_pinyin"):
            out["mainland_pinyin"] = hit["mainland_pinyin"]
    for k, v in base.items():
        if k not in ("trad", "pinyin", "zhuyin") and v not in (None, ""):
            out[k] = v
    tw = content_store.taiwan_vocab_index().get(word)
    if tw:
        for k in ("mainland", "note", "register", "example"):
            if tw.get(k) and not out.get(k):
                out[k] = tw[k]
        out["tw"] = True
    return out


# ----------------------------------------------------------------------------------------------
# HSK lists
# ----------------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _hsk_raw() -> list[dict]:
    p = RAW_DIR / "hsk_complete.json"
    if not p.exists():
        dictionary._download(dictionary.HSK_URL, p)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def hsk_words() -> dict[int, list[dict]]:
    """Old-HSK level -> [{trad, simp, pinyin, en, rank}] sorted by frequency rank."""
    out: dict[int, list[dict]] = {i: [] for i in range(1, 7)}
    for item in _hsk_raw():
        lv = [int(x.split("-")[1]) for x in item.get("level", []) if x.startswith("old-")]
        if not lv or not item.get("forms"):
            continue
        f = item["forms"][0]
        simp = item["simplified"]
        out[min(lv)].append({
            "trad": text.to_traditional(simp), "plain": text._s2t.convert(simp), "simp": simp,
            "en": "; ".join(f.get("meanings", [])[:3]), "rank": item.get("frequency") or 99999,
        })
    for lv in out:
        out[lv].sort(key=lambda x: x["rank"])
    return out


def seed_known_words(max_level: int = 5) -> int:
    """The learner already knows HSK 1..max_level: record those words (in Traditional) as known."""
    if db.q1("SELECT 1 x FROM words WHERE source='hsk-seed' LIMIT 1"):
        return 0
    rows = []
    for lv in range(1, max_level + 1):
        for w in hsk_words()[lv]:
            rows.append((w["trad"], "known", "hsk-seed", db.now()))
    db.exmany("INSERT OR IGNORE INTO words(word,status,source,added_at) VALUES(?,?,?,?)", rows)
    return len(rows)


# ----------------------------------------------------------------------------------------------
# Simplified -> Traditional bridge
# ----------------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def bridge_units() -> list[dict]:
    """Daily units of the character bridge. Each unit: optional component family, optional
    one-to-many split, and a handful of individual characters with example words."""
    b = content_store.s2t_bridge()
    fams = list(b.get("component_families", []))
    splits = list(b.get("one_to_many", []))
    curated = [{"s": x["s"], "t": x["t"], "words": x.get("words", [])} for x in b.get("whole_char", [])]

    covered = {x["t"] for x in curated}
    for f in fams:
        for s, t in f.get("examples", []):
            covered.update(c for c in t)
    for sp in splits:
        covered.update(o["t"] for o in sp["options"])

    # Every other changed character in HSK 1-6, by level then frequency.
    auto: dict[str, dict] = {}
    for lv in range(1, 7):
        for w in hsk_words()[lv]:
            s, t = w["simp"], w["trad"]
            if len(s) != len(t):
                continue
            for cs, ct in zip(s, t):
                if cs == ct or not HAN.match(ct):
                    continue
                e = auto.setdefault(ct, {"s": cs, "t": ct, "words": [], "lv": lv})
                if len(e["words"]) < 3 and t not in e["words"]:
                    e["words"].append(t)
    extra = [e for t, e in auto.items() if t not in covered]
    chars = curated + extra

    units = []
    per = 6
    while fams or splits or chars:
        u: dict = {"n": len(units) + 1}
        if fams:
            u["family"] = fams.pop(0)
        if splits and (len(units) % 2 == 0 or not fams):
            u["split"] = splits.pop(0)
        size = per if (u.get("family") or u.get("split")) else per + 3
        u["chars"], chars = chars[:size], chars[size:]
        units.append(u)
    return units


def bridge_total_chars() -> int:
    return sum(len(unit_cards(u)) for u in bridge_units())


def unit_cards(u: dict) -> list[dict]:
    """The character cards a bridge unit introduces."""
    cards = []
    if u.get("family"):
        f = u["family"]
        for s, t in f.get("examples", [])[:4]:
            # the changed character(s) of each example word
            for cs, ct in zip(s, t):
                if cs != ct:
                    cards.append({"t": ct, "s": cs, "words": [t], "tip": f"{f['simplified']} → {f['traditional']}"})
                    break
    if u.get("split"):
        sp = u["split"]
        for o in sp["options"]:
            if o["t"] != sp["s"]:
                cards.append({"t": o["t"], "s": sp["s"], "words": o.get("words", [])[:3],
                              "tip": f"{o['meaning']}. {sp.get('tip', '')}".strip()})
    for c in u.get("chars", []):
        cards.append({"t": c["t"], "s": c["s"], "words": c.get("words", [])[:3], "tip": ""})
    seen, out = set(), []
    for c in cards:
        if c["t"] in seen:
            continue
        seen.add(c["t"])
        out.append(c)
    return out


def bridge_unit_payload(idx: int) -> dict | None:
    units = bridge_units()
    if idx >= len(units):
        return None
    u = units[idx]
    cards = unit_cards(u)
    for c in cards:
        info = describe(c["t"])
        c["pinyin"], c["zhuyin"] = info.get("pinyin", ""), info.get("zhuyin", "")
        c["en"] = info.get("en", "")
        c["word_info"] = [_brief(w) for w in c["words"]]
    out = {"n": u["n"], "total": len(units), "cards": cards}
    if u.get("family"):
        f = u["family"]
        out["family"] = {"simplified": f["simplified"], "traditional": f["traditional"], "note": f.get("note", ""),
                         "examples": [{"s": s, "t": t, **_brief(t)} for s, t in f.get("examples", [])]}
    if u.get("split"):
        sp = u["split"]
        out["split"] = {"s": sp["s"], "tip": sp.get("tip", ""),
                        "options": [{"t": o["t"], "meaning": o["meaning"], "words": [_brief(w) for w in o.get("words", [])]}
                                    for o in sp["options"]]}
    return out


def _brief(word: str) -> dict:
    d = describe(word)
    return {"trad": word, "simp": d.get("simp") or word, "pinyin": d.get("pinyin", ""), "zhuyin": d.get("zhuyin", ""),
            "en": d.get("en", "")}


# ----------------------------------------------------------------------------------------------
# Word decks
# ----------------------------------------------------------------------------------------------

def _introduced(kind: str) -> set[str]:
    return {r["key"] for r in db.q("SELECT key FROM cards WHERE kind=?", (kind,))}


@lru_cache(maxsize=1)
def cedict_tw_words() -> list[dict]:
    """Words CC-CEDICT marks as Taiwan usage, beyond the curated list. Most frequent first."""
    rows = dictionary._conn().execute(
        "SELECT trad, simp, defs, freq FROM entries WHERE defs LIKE '%(Tw)%' AND length(trad) BETWEEN 2 AND 4 "
        "ORDER BY freq DESC"
    ).fetchall()
    out, seen = [], set()
    for r in rows:
        defs = json.loads(r["defs"])
        tw_defs = [d for d in defs if "(Tw)" in d]
        # keep entries whose main sense is Taiwan usage
        if not tw_defs or (len(defs) > 3 and defs.index(tw_defs[0]) > 1):
            continue
        if r["trad"] in seen or re.search(r"[A-Za-z0-9]", r["trad"]):
            continue
        seen.add(r["trad"])
        en = re.sub(r"\s*\(Tw\)\s*", " ", "; ".join(tw_defs[:2])).strip()
        en = re.sub(r"\[[^\]]*\]", "", re.sub(r"(\S+)\|(\S+?)(?=\[|\s|$)", r"\1", en))
        out.append({"trad": r["trad"], "en": en[:120], "category": "cedict", "level": 3, "register": "neutral"})
    return out


def tw_deck() -> list[dict]:
    """Curated Taiwan vocabulary, interleaving categories inside each level, then CEDICT extras."""
    curated = content_store.taiwan_vocab()
    out = []
    for lv in (1, 2, 3):
        buckets: dict[str, list[dict]] = {}
        for x in curated:
            if x.get("level", 2) == lv and x.get("register") != "vulgar":
                buckets.setdefault(x.get("category", ""), []).append(x)
        while buckets:
            for cat in list(buckets):
                out.append(buckets[cat].pop(0))
                if not buckets[cat]:
                    del buckets[cat]
    out += [x for x in curated if x.get("register") == "vulgar"]
    have = {x["trad"] for x in out}
    out += [x for x in cedict_tw_words() if x["trad"] not in have]
    return out


def hsk6_deck() -> list[dict]:
    return hsk_words()[6]


def book_deck() -> list[dict]:
    """Companion-pack vocabulary first, then words mined from the imported text in reading order."""
    pack = content_store.book_pack().get("vocab", [])
    out = sorted(pack, key=lambda x: x.get("level", 2))
    have = {x["trad"] for x in out}
    mined = db.get_setting("book_words", []) or []
    out += [{"trad": w} for w in mined if w not in have]
    return out


def next_words(deck: str, n: int) -> list[dict]:
    if n <= 0:
        return []
    src = {"tw": tw_deck, "hsk6": hsk6_deck, "book": book_deck}[deck]()
    have = _introduced("word")
    known = db.known_words() if deck == "book" else set()
    out = []
    for x in src:
        w = x["trad"]
        if w in have or (deck == "book" and w in known and x.get("level", 2) != 1):
            continue
        rec = describe(w, x)
        rec["deck"] = deck
        out.append(rec)
        have.add(w)
        if len(out) >= n:
            break
    return out


def next_pron(n: int) -> list[dict]:
    have = _introduced("pron")
    out = []
    for x in sorted(content_store.pronunciation_diffs(), key=lambda x: (x.get("common", 2), x.get("status") != "standard")):
        if x["trad"] in have:
            continue
        rec = dict(x)
        rec["tw_zhuyin"] = " ".join(pinyin_to_zhuyin(s) for s in x.get("tw", "").split())
        out.append(rec)
        if len(out) >= n:
            break
    return out


def next_grammar(phase: int) -> dict | None:
    done = set(db.get_setting("grammar_done", []) or [])
    pts = content_store.grammar_points()
    max_level = 1 if phase <= 1 else 2 if phase == 2 else 3
    for p in pts:
        if p["id"] not in done and p.get("level", 1) <= max_level:
            return p
    for p in pts:
        if p["id"] not in done:
            return p
    return None


def mark_grammar(gid: str) -> None:
    done = db.get_setting("grammar_done", []) or []
    if gid not in done:
        done.append(gid)
        db.set_setting("grammar_done", done)


# ----------------------------------------------------------------------------------------------
# Cards
# ----------------------------------------------------------------------------------------------

def add_word_card(rec: dict, source: str = "") -> int | None:
    data = {k: rec.get(k) for k in ("trad", "simp", "pinyin", "zhuyin", "en", "deck", "example", "note", "mainland",
                                     "category", "register", "mainland_pinyin") if rec.get(k)}
    return srs.add_card("word", rec["trad"], data, source=source or rec.get("deck", ""))


def add_char_card(c: dict, source: str = "bridge") -> int | None:
    data = {k: c.get(k) for k in ("t", "s", "words", "tip", "pinyin", "zhuyin", "en", "word_info") if c.get(k)}
    return srs.add_card("char", c["t"], data, source=source)


def add_pron_card(p: dict) -> int | None:
    return srs.add_card("pron", p["trad"], p, source="pron")


def add_sentence_card(zh: str, en: str, source: str = "") -> int | None:
    return srs.add_card("sentence", zh, {"zh": zh, "en": en}, source=source)


def deck_stats() -> dict:
    kinds = {r["kind"]: r for r in db.q(
        "SELECT kind, count(*) n, sum(interval>=21) mature, sum(reps>0) started FROM cards GROUP BY kind")}
    by_deck = {r["source"]: r["n"] for r in db.q("SELECT source, count(*) n FROM cards WHERE kind='word' GROUP BY source")}
    units = bridge_units()
    return {
        "char": {"learned": (kinds.get("char") or {}).get("n", 0), "total": bridge_total_chars(),
                 "units": len(units), "unit_ptr": db.get_setting("bridge_ptr", 0)},
        "tw": {"learned": by_deck.get("tw", 0), "total": len(tw_deck()), "curated": len(content_store.taiwan_vocab())},
        "hsk6": {"learned": by_deck.get("hsk6", 0), "total": len(hsk6_deck())},
        "book": {"learned": by_deck.get("book", 0), "total": len(book_deck())},
        "pron": {"learned": (kinds.get("pron") or {}).get("n", 0), "total": len(content_store.pronunciation_diffs())},
        "grammar": {"learned": len(db.get_setting("grammar_done", []) or []), "total": len(content_store.grammar_points())},
        "mature": sum((k.get("mature") or 0) for k in kinds.values()),
        "cards": sum(k["n"] for k in kinds.values()),
    }
