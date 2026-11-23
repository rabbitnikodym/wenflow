"""Wenflow API server. Run from server/:  uv run uvicorn wenflow.main:app --port 8000"""
from __future__ import annotations

import json
import logging
import random
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (config, content_store, curriculum, db, decks, dictionary, g2p, lessons, library, llm, srs, text, tts,
               tutor, video, voice_local, zhuyin_course)
from .zhuyin import pinyin_to_zhuyin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("wenflow")

DEFAULT_SETTINGS = {
    "ruby": "zhuyin",          # zhuyin | pinyin | none
    "pinyin_support": True,    # with zhuyin: keep pinyin on syllables whose symbols are not learned yet
    "tone_colors": False,
    "show_simplified": True,   # show the Simplified form in word popups
    "tts_voice": config.TTS_VOICE,
    "tts_rate": 0,
    "theme": "dark",
    "builtin_ime": True,
    "hanzi_font": "serif",     # serif (明體) | sans (黑體) | kai (楷體)
    "llm_model": config.LLM_MODEL,
}


def _warm() -> None:
    try:
        dictionary.build()
        decks.seed_known_words()
        g2p.load()
        text.annotate("暖機一下，確認注音標註沒問題。")
        zhuyin_course._word_bank()  # readings for every HSK 1-5 word (cached on disk after the first run)
        g2p.readings_many([x["trad"] for x in content_store.taiwan_vocab()] + [w["trad"] for w in decks.hsk6_deck()[:600]])
    except Exception as e:  # noqa: BLE001
        log.warning("warm-up: %s", e)
    try:
        from . import speech

        speech._get_model()
    except Exception as e:  # noqa: BLE001
        log.warning("whisper preload: %s", e)
    try:
        if settings()["tts_voice"] == voice_local.VOICE_ID:
            voice_local.start()
    except Exception as e:  # noqa: BLE001
        log.warning("local voice: %s", e)
    try:  # the 37 symbol-name clips are generated once, on first start
        if len(list((config.DATA_DIR / "symbols").glob("*"))) < 37:
            import subprocess
            import sys

            subprocess.run([sys.executable, str(config.ROOT / "server" / "scripts" / "build_symbol_audio.py")],
                           cwd=str(config.ROOT / "server"), timeout=600, check=False, capture_output=True)
    except Exception as e:  # noqa: BLE001
        log.warning("symbol clips: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    threading.Thread(target=_warm, daemon=True).start()
    yield
    voice_local.stop()


app = FastAPI(title="Wenflow", lifespan=lifespan)


def settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    if voice_local.installed():  # the local Taiwanese voice is the default once it is installed
        s["tts_voice"] = voice_local.VOICE_ID
    s.update(db.get_setting("ui", {}) or {})
    if s["tts_voice"] == voice_local.VOICE_ID and not voice_local.installed():
        s["tts_voice"] = config.TTS_VOICE
    return s


def voices() -> dict:
    v = dict(tts.EDGE_VOICES)
    if voice_local.installed():
        v = {voice_local.VOICE_ID: voice_local.VOICE_LABEL, **v}
    return v


# ----------------------------------------------------------------------------------------------
# State & settings
# ----------------------------------------------------------------------------------------------

@app.get("/api/state")
def state():
    from . import speech

    return {
        "settings": settings(), "summary": lessons.summary(), "srs": srs.counts(),
        "services": {"llm": llm.available(), "llm_model": llm.model(), "whisper": speech.whisper_status(),
                     "g2p": g2p.status(), "tts_voices": voices(), "local_voice": voice_local.status()},
        "book": _book_state(), "zhuyin": zhuyin_course.progress(),
    }


def _book_state() -> dict:
    bid = db.get_setting("active_book")
    pack = content_store.book_pack()
    out = {"imported": False, "pack_title": pack.get("title", ""), "pack_words": len(pack.get("vocab", []))}
    if bid:
        b = next((x for x in library.list_books() if x["id"] == bid), None)
        if b:
            out.update({"imported": True, "id": bid, "title": b["title"], "progress": b["progress"], "stats": b["meta"].get("stats")})
    return out


class SettingsIn(BaseModel):
    values: dict


@app.post("/api/settings")
def save_settings(body: SettingsIn):
    cur = db.get_setting("ui", {}) or {}
    cur.update({k: v for k, v in body.values.items() if k in DEFAULT_SETTINGS})
    db.set_setting("ui", cur)
    if "llm_model" in body.values:
        db.set_setting("llm_model", body.values["llm_model"])
        db.set_setting("llm_fast_model", body.values["llm_model"])
    return settings()


# ----------------------------------------------------------------------------------------------
# Lessons & curriculum
# ----------------------------------------------------------------------------------------------

_warmed: set[str] = set()


def _warm_audio(plan: dict) -> None:
    """Prepare the lesson's audio in the background so the first tap of each word is instant."""
    import asyncio

    voice = settings()["tts_voice"]
    tag = f"{plan.get('day')}|{voice}"
    if tag in _warmed or voice != voice_local.VOICE_ID:
        return
    _warmed.add(tag)
    texts: list[str] = []
    for b in plan.get("blocks", []):
        p = b.get("payload", {})
        for w in p.get("words", []) or []:
            texts += [w.get("trad", ""), (w.get("example") or {}).get("zh", "")]
        for s_ in p.get("sentences", []) or []:
            texts.append(s_.get("zh", "") if isinstance(s_, dict) else s_)
        for c in p.get("cards", []) or []:
            texts += (c.get("words") or [])[:1]
        for it in p.get("items", []) or []:
            if isinstance(it, dict):
                texts += [it.get("trad", ""), it.get("text", ""), (it.get("example") or {}).get("zh", "")]
        for ex in (p.get("point") or {}).get("examples", []) or []:
            texts.append(ex.get("zh", ""))
    texts = list(dict.fromkeys(t for t in texts if t))

    def run():
        if not voice_local.wait_ready(180):
            _warmed.discard(tag)
            return
        for t in texts:
            try:
                asyncio.run(tts.synthesize(t, voice=voice))
            except Exception as e:  # noqa: BLE001
                log.info("audio warm-up skipped %r: %s", t[:16], e)

    threading.Thread(target=run, daemon=True).start()


@app.get("/api/lesson/today")
def lesson_today():
    plan = lessons.today()
    _warm_audio(plan)
    return plan


@app.post("/api/lesson/next")
def lesson_next():
    return lessons.start_next()


@app.get("/api/lesson/{day}")
def lesson_get(day: int):
    r = lessons.get(day)
    if not r:
        raise HTTPException(404, "No such lesson yet")
    return r


class BlockDone(BaseModel):
    data: dict = {}


@app.post("/api/lesson/{day}/block/{block_id}")
def lesson_block(day: int, block_id: str, body: BlockDone):
    try:
        return lessons.complete_block(day, block_id, body.data)
    except KeyError:
        raise HTTPException(404, "No such block")


@app.get("/api/lessons")
def lesson_history():
    rows = db.q("SELECT day, date, status, plan, progress FROM lessons ORDER BY day DESC LIMIT 400")
    out = []
    for r in rows:
        plan, prog = json.loads(r["plan"] or "{}"), json.loads(r["progress"] or "{}")
        out.append({"day": r["day"], "date": r["date"], "status": r["status"], "week": plan.get("week"),
                    "title": plan.get("week_title"), "blocks": len(plan.get("blocks", [])),
                    "done": sum(1 for v in prog.values() if v.get("done"))})
    return out


@app.get("/api/curriculum")
def get_curriculum():
    return {"phases": curriculum.PHASES, "weeks": curriculum.overview(), "summary": lessons.summary()}


# ----------------------------------------------------------------------------------------------
# Zhuyin course, typing, input method
# ----------------------------------------------------------------------------------------------

@app.get("/api/zhuyin")
def zhuyin_overview():
    return zhuyin_course.overview()


@app.get("/api/zhuyin/unit/{n}")
def zhuyin_unit(n: int, seed: int | None = None):
    u = zhuyin_course.unit_payload(n, seed)
    if not u:
        raise HTTPException(404, "No such unit")
    return u


@app.post("/api/zhuyin/unit/{n}/done")
def zhuyin_done(n: int):
    zhuyin_course.mark_done(n)
    db.log_activity("zhuyin", 300, {"unit": n})
    return {"ok": True}


@app.get("/api/typing/sentences")
def typing_sentences(n: int = 6):
    return zhuyin_course.typing_sentences(n)


class TypingStat(BaseModel):
    mode: str = "practice"
    chars: int
    seconds: float
    accuracy: float


@app.post("/api/typing/stat")
def typing_stat(body: TypingStat):
    db.ex("INSERT INTO typing_stats(ts,mode,chars,seconds,accuracy) VALUES(?,?,?,?,?)",
          (db.now(), body.mode, body.chars, body.seconds, body.accuracy))
    db.log_activity("typing", int(body.seconds), {"chars": body.chars})
    return {"ok": True}


class ImeIn(BaseModel):
    keys: list[str]
    hint: str = ""
    expect: str = ""


@app.post("/api/ime")
def ime(body: ImeIn):
    return dictionary.ime_convert(body.keys[:40], hint=body.hint, expect=body.expect)


# ----------------------------------------------------------------------------------------------
# Dictionary, annotation, speech synthesis
# ----------------------------------------------------------------------------------------------

class TextIn(BaseModel):
    text: str
    gloss: bool = True


@app.post("/api/annotate")
def annotate(body: TextIn):
    t = text.ensure_traditional(body.text)
    return {"text": t, "paragraphs": [text.annotate(p, body.gloss) for p in t.split("\n") if p.strip()]}


@app.get("/api/dict")
def dict_lookup(w: str):
    w = w.strip()
    info = decks.describe(w)
    entries = dictionary.lookup(w)[:6]
    for e in entries:
        e["defs"] = e["defs"][:8]
    card = db.q1("SELECT id, interval, reps, due FROM cards WHERE kind='word' AND key=?", (w,))
    st = db.q1("SELECT status FROM words WHERE word=?", (w,))
    pron = next((p for p in content_store.pronunciation_diffs() if p.get("trad") == w), None)
    chars = []
    if len(w) > 1:
        for c in w:
            if text.HAN_RE.match(c):
                d = decks.describe(c)
                chars.append({"c": c, "pinyin": d.get("pinyin"), "zhuyin": d.get("zhuyin"), "en": d.get("en", "")[:80], "simp": d.get("simp")})
    return {"word": w, "info": info, "entries": entries, "card": card, "status": st and st["status"],
            "tw": content_store.taiwan_vocab_index().get(w), "pron": pron, "chars": chars}


@app.get("/api/moedict")
def moedict(w: str):
    """Taiwan Ministry of Education dictionary definitions (in Chinese), via moedict.tw."""
    import httpx

    cache = db.get_setting(f"moe:{w}")
    if cache is not None:
        return cache
    out: dict = {"word": w, "heteronyms": []}
    try:
        r = httpx.get(f"https://www.moedict.tw/a/{w}.json", timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            strip = lambda s: (s or "").replace("`", "").replace("~", "")  # noqa: E731
            for h in r.json().get("h", [])[:3]:
                out["heteronyms"].append({
                    "bopomofo": strip(h.get("b")), "pinyin": strip(h.get("p")),
                    "defs": [{"type": strip(d.get("type")), "def": strip(d.get("f")),
                              "examples": [strip(e) for e in (d.get("e") or [])][:2]} for d in h.get("d", [])[:6]]})
    except Exception as e:  # noqa: BLE001
        log.info("moedict %s: %s", w, e)
        return out
    db.set_setting(f"moe:{w}", out)
    return out


@app.get("/api/tts")
async def speak(text_: str | None = None, text: str | None = None, rate: int | None = None, voice: str | None = None):
    t = (text or text_ or "").strip()
    if not t:
        raise HTTPException(400, "text required")
    s = settings()
    try:
        data = await tts.synthesize(t[:600], voice=voice or s["tts_voice"], rate=s["tts_rate"] if rate is None else rate)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"speech synthesis failed: {e}")
    if not data:
        raise HTTPException(502, "speech synthesis returned no audio")
    local = data[:4] == b"RIFF"
    # A clip made by the cloud voice only because the local one was still loading must not stick in the browser.
    stand_in = (voice or s["tts_voice"]) == voice_local.VOICE_ID and not local and not voice_local.status()["ready"]
    return Response(data, media_type="audio/wav" if local else "audio/mpeg",
                    headers={"Cache-Control": "no-store" if stand_in else "public, max-age=604800"})


@app.post("/api/voice/start")
def voice_start():
    """Start the local voice (it takes about half a minute to load) and report its state."""
    voice_local.start()
    return voice_local.status()


@app.get("/api/tts/symbol/{sym}")
async def speak_symbol(sym: str):
    """The name of a zhuyin symbol (bo, po, mo, fo ...), from the clips recorded by scripts/build_symbol_audio.py."""
    if len(sym) != 1 or not ("\u3105" <= sym <= "\u3129"):
        raise HTTPException(404, "Not a zhuyin symbol")
    for ext, mime in ((".mp3", "audio/mpeg"), (".wav", "audio/wav")):
        f = config.DATA_DIR / "symbols" / f"{ord(sym):04x}{ext}"
        if f.exists():
            return FileResponse(f, media_type=mime, headers={"Cache-Control": "public, max-age=604800"})
    data = await tts.synthesize(sym, voice="zh-TW-HsiaoChenNeural", rate=-8)
    return Response(data, media_type="audio/mpeg")


class ExplainIn(BaseModel):
    word: str
    sentence: str = ""


@app.post("/api/explain")
def explain(body: ExplainIn):
    out = llm.chat_json(
        "You are a Taiwanese Mandarin teacher. The learner knows mainland Mandarin (HSK 5, Simplified) and is learning "
        "Taiwan usage. Explain briefly and concretely in English; all Chinese in Traditional characters with Taiwan wording. "
        'Output JSON: {"meaning":"what it means here, 1-2 sentences","nuance":"register, connotation, and how mainland usage '
        'differs if it does, else empty","examples":[{"zh":"…","en":"…"},{"zh":"…","en":"…"}],"similar":["近義詞 or the mainland equivalent"]}',
        json.dumps({"word": body.word, "sentence": body.sentence}, ensure_ascii=False), fast=True)
    for ex in out.get("examples", []) or []:
        if isinstance(ex, dict) and ex.get("zh"):
            ex["zh"] = text.ensure_traditional(ex["zh"])
            ex["tokens"] = text.annotate(ex["zh"], False)
    return out


@app.post("/api/translate")
def translate(body: TextIn):
    out = llm.chat([{"role": "system", "content": "Translate the Taiwanese Mandarin text into natural English. Output only the translation."},
                    {"role": "user", "content": body.text[:3000]}], fast=True)
    return {"en": out.strip()}


class WritingIn(BaseModel):
    text: str
    prompt: str = ""
    must_use: list[str] = []


@app.post("/api/writing/feedback")
def writing_feedback(body: WritingIn):
    out = llm.chat_json(
        llm.TW_STYLE + "\n你是台灣的華語寫作老師。學習者原本學中國大陸的普通話，現在學台灣華語和繁體字。請批改他寫的文字。"
        "輸出 JSON：{\"corrected\":\"修正錯字、文法、用詞後的版本（保留原意和大致長度）\","
        "\"natural\":\"台灣人會怎麼寫（更道地、更順）\",\"score\":1到5的整數,"
        "\"issues\":[{\"type\":\"wrong-character|mainland-term|grammar|word-choice|punctuation\",\"said\":\"原文片段\",\"better\":\"建議\",\"why\":\"short English\"}],"
        "\"comment\":\"2 short English sentences: what was good and the one thing to fix first\"}。"
        "特別留意：簡體字或用錯的繁體字（例如 頭發→頭髮、以后→以後、里面→裡面）、大陸用語、標點符號（要用全形，引號用「」）。",
        json.dumps({"task": body.prompt, "must_use": body.must_use, "text": body.text[:3000]}, ensure_ascii=False))
    res = {"corrected": text.ensure_traditional(str(out.get("corrected", ""))),
           "natural": text.ensure_traditional(str(out.get("natural", ""))),
           "score": out.get("score") if isinstance(out.get("score"), int) else None,
           "comment": str(out.get("comment", "")), "issues": []}
    for it in out.get("issues") or []:
        if isinstance(it, dict) and it.get("better"):
            res["issues"].append({k: str(it.get(k, "")) for k in ("type", "said", "better", "why")})
    res["natural_tokens"] = text.annotate(res["natural"], False) if res["natural"] else []
    res["used"] = {w: (w in body.text) for w in body.must_use}
    db.log_activity("writing", 120, {"chars": len(body.text)})
    return res


# ----------------------------------------------------------------------------------------------
# Speech recognition and tone analysis
# ----------------------------------------------------------------------------------------------

@app.post("/api/speech/analyze")
async def speech_analyze(audio: UploadFile = File(...), target: str = Form("")):
    data = await audio.read()

    def run():
        from . import speech

        a = speech.decode_audio(data)
        if len(a) < speech.SR * 0.3:
            return {"error": "The recording was too short."}
        tgt = text.ensure_traditional(target.strip()) or None
        res = speech.analyze_tones(a, tgt)
        res.pop("templates", None)
        res["heard_tokens"] = text.annotate(res["asr"]["text"], False) if res.get("asr") else []
        return res

    import anyio

    try:
        return await anyio.to_thread.run_sync(run)
    except Exception as e:  # noqa: BLE001
        log.exception("speech analyze failed")
        raise HTTPException(500, f"Could not analyse the recording: {e}")


@app.post("/api/speech/transcribe")
async def speech_transcribe(audio: UploadFile = File(...)):
    data = await audio.read()

    def run():
        from . import speech

        r = speech.transcribe(speech.decode_audio(data), word_timestamps=False)
        return {"text": r["text"], "tokens": text.annotate(r["text"])}

    import anyio

    return await anyio.to_thread.run_sync(run)


# ----------------------------------------------------------------------------------------------
# Spaced repetition and vocabulary
# ----------------------------------------------------------------------------------------------

def _hydrate_card(c: dict) -> dict:
    d = c["data"]
    if c["kind"] == "word" and isinstance(d.get("example"), dict) and d["example"].get("zh"):
        d["example"]["tokens"] = text.annotate(d["example"]["zh"], False)
    if c["kind"] == "sentence":
        d["tokens"] = text.annotate(d["zh"], False)
    if c["kind"] == "pron" and not d.get("tw_zhuyin"):
        d["tw_zhuyin"] = " ".join(pinyin_to_zhuyin(s) for s in d.get("tw", "").split())
    c["new"] = c["reps"] == 0 and not c["last_review"]
    return c


@app.get("/api/srs/due")
def srs_due(limit: int = 40, kinds: str = ""):
    ks = [k for k in kinds.split(",") if k] or None
    cards = [_hydrate_card(c) for c in srs.due_cards(limit, ks)]
    return {"cards": cards, "counts": srs.counts()}


class ReviewIn(BaseModel):
    id: int
    grade: int
    mode: str = ""


@app.post("/api/srs/review")
def srs_review(body: ReviewIn):
    try:
        r = srs.review(body.id, max(1, min(4, body.grade)), body.mode)
    except KeyError:
        raise HTTPException(404, "No such card")
    db.log_activity("review", 8, None)
    return r


class AddWord(BaseModel):
    word: str
    sentence: str = ""
    source: str = "manual"


@app.post("/api/srs/add")
def srs_add(body: AddWord):
    w = body.word.strip()
    if not w:
        raise HTTPException(400, "word required")
    rec = decks.describe(w)
    rec["deck"] = body.source
    if body.sentence and not rec.get("example"):
        rec["example"] = {"zh": body.sentence, "en": ""}
    cid = decks.add_word_card(rec, source=body.source)
    db.ex("INSERT INTO words(word,status,source,added_at) VALUES(?,?,?,?) ON CONFLICT(word) DO UPDATE SET status='learning'",
          (w, "learning", body.source, db.now()))
    return {"id": cid, "card": rec}


class WordStatus(BaseModel):
    word: str
    status: str  # known | learning | unknown


@app.post("/api/words")
def word_status(body: WordStatus):
    if body.status == "unknown":
        db.ex("DELETE FROM words WHERE word=?", (body.word,))
    else:
        db.ex("INSERT INTO words(word,status,source,added_at) VALUES(?,?,?,?) ON CONFLICT(word) DO UPDATE SET status=excluded.status",
              (body.word, body.status, "manual", db.now()))
    return {"ok": True}


@app.delete("/api/srs/card/{cid}")
def srs_delete(cid: int):
    db.ex("DELETE FROM cards WHERE id=?", (cid,))
    return {"ok": True}


@app.get("/api/vocab/taiwan")
def vocab_taiwan():
    have = {r["key"]: r for r in db.q("SELECT key, interval, reps FROM cards WHERE kind='word'")}
    out = []
    for x in content_store.taiwan_vocab():
        syls = (x.get("pinyin") or "").split()
        out.append({**x, "zhuyin": " ".join(pinyin_to_zhuyin(s) for s in syls),
                    "learning": x["trad"] in have, "mature": (have.get(x["trad"]) or {}).get("interval", 0) >= 21})
    cats = sorted({x.get("category", "") for x in out})
    return {"items": out, "categories": cats, "extra": len(decks.cedict_tw_words())}


@app.get("/api/vocab/pron")
def vocab_pron():
    have = {r["key"] for r in db.q("SELECT key FROM cards WHERE kind='pron'")}
    out = []
    for x in content_store.pronunciation_diffs():
        out.append({**x, "cn": x.get("cn") or x.get("mainland", ""),
                    "tw_zhuyin": " ".join(pinyin_to_zhuyin(s) for s in x.get("tw", "").split()), "learning": x["trad"] in have})
    return {"items": out}


@app.get("/api/vocab/grammar")
def vocab_grammar():
    done = set(db.get_setting("grammar_done", []) or [])
    return {"items": [{**g, "done": g["id"] in done} for g in content_store.grammar_points()]}


@app.get("/api/vocab/bridge")
def vocab_bridge():
    b = content_store.s2t_bridge()
    have = {r["key"] for r in db.q("SELECT key FROM cards WHERE kind='char'")}
    return {"units": len(decks.bridge_units()), "ptr": db.get_setting("bridge_ptr", 0), "learned": len(have),
            "total": decks.bridge_total_chars(), "families": b.get("component_families", []),
            "one_to_many": b.get("one_to_many", []), "variants": b.get("taiwan_variants", [])}


@app.get("/api/vocab/bridge/{n}")
def vocab_bridge_unit(n: int):
    u = decks.bridge_unit_payload(n - 1)
    if not u:
        raise HTTPException(404, "No such unit")
    return u


@app.get("/api/vocab/cards")
def vocab_cards(kind: str = "word", q: str = "", limit: int = 300):
    rows = db.q("SELECT id, kind, key, data, due, interval, reps, lapses, source FROM cards WHERE kind=? AND key LIKE ? "
                "ORDER BY id DESC LIMIT ?", (kind, f"%{q}%", limit))
    for r in rows:
        r["data"] = json.loads(r["data"])
    return {"cards": rows, "counts": srs.counts()}


# ----------------------------------------------------------------------------------------------
# Videos
# ----------------------------------------------------------------------------------------------

class UrlIn(BaseModel):
    url: str


@app.get("/api/videos")
def videos():
    return {"videos": video.library(), "today": [v["id"] for v in video.todays()], "target_level": video.target_level()}


@app.get("/api/videos/daily")
def videos_daily(force: bool = False):
    return {"videos": video.discover(force), "target_level": video.target_level()}


@app.post("/api/videos/import")
def videos_import(body: UrlIn):
    try:
        return video.start_import(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/videos/upload")
async def videos_upload(file: UploadFile = File(...)):
    data = await file.read()
    return video.import_local(file.filename or "video.mp4", data)


@app.get("/api/videos/{vid}")
def videos_get(vid: str):
    v = video.get(vid)
    if not v:
        raise HTTPException(404, "No such video")
    return v


@app.get("/api/videos/{vid}/job")
def videos_job(vid: str):
    return video.job(vid)


class Watched(BaseModel):
    seconds: int = 0


@app.post("/api/videos/{vid}/watched")
def videos_watched(vid: str, body: Watched):
    video.mark_watched(vid, body.seconds)
    return {"ok": True}


@app.delete("/api/videos/{vid}")
def videos_delete(vid: str):
    video.delete(vid)
    return {"ok": True}


# ----------------------------------------------------------------------------------------------
# Library: books, articles, news
# ----------------------------------------------------------------------------------------------

@app.get("/api/library")
def get_library():
    pack = content_store.book_pack()
    return {"books": library.list_books(), "readings": library.list_readings(),
            "pack": {k: pack.get(k) for k in ("title", "author", "year", "about", "reading_tips", "characters", "culture_notes")},
            "pack_words": len(pack.get("vocab", []))}


@app.get("/api/news")
def news(refresh: bool = False):
    return {"items": library.discover(refresh=refresh)}


class ReadingIn(BaseModel):
    url: str = ""
    text: str = ""
    title: str = ""


@app.post("/api/readings")
def reading_add(body: ReadingIn):
    try:
        if body.url.strip():
            return {"id": library.import_url(body.url.strip())}
        if len(body.text.strip()) < 10:
            raise HTTPException(400, "Paste some text or a link.")
        return {"id": library.add_reading(body.title, body.text)}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not import: {e}")


@app.get("/api/readings/{rid}")
def reading_get(rid: int):
    r = library.get_reading(rid)
    if not r:
        raise HTTPException(404, "No such reading")
    return r


@app.post("/api/readings/{rid}/read")
def reading_read(rid: int, body: Watched):
    db.ex("UPDATE readings SET read_at=? WHERE id=?", (db.now(), rid))
    db.log_activity("reading", body.seconds or 300, {"reading": rid})
    return {"ok": True}


@app.post("/api/readings/{rid}/questions")
def reading_questions(rid: int):
    r = db.q1("SELECT title, text FROM readings WHERE id=?", (rid,))
    if not r:
        raise HTTPException(404, "No such reading")
    qs = library.make_questions(r["title"], r["text"])
    db.ex("UPDATE readings SET questions=? WHERE id=?", (json.dumps(qs, ensure_ascii=False), rid))
    return {"questions": qs}


@app.delete("/api/readings/{rid}")
def reading_delete(rid: int):
    db.ex("DELETE FROM readings WHERE id=?", (rid,))
    return {"ok": True}


@app.post("/api/books/upload")
async def book_upload(file: UploadFile = File(...), title: str = Form(""), author: str = Form("")):
    data = await file.read()
    try:
        bid = library.import_book_file(file.filename or "book.txt", data, title, author)
    except Exception as e:  # noqa: BLE001
        log.exception("book import failed")
        raise HTTPException(400, f"Could not read that file: {e}")
    return {"id": bid}


class BookText(BaseModel):
    title: str
    author: str = ""
    text: str


@app.post("/api/books/text")
def book_text(body: BookText):
    if len(body.text) < 200:
        raise HTTPException(400, "That text is too short to be a book.")
    return {"id": library.import_book_text(body.title or "Untitled", body.author, body.text)}


@app.delete("/api/books/{bid}")
def book_delete(bid: int):
    library.delete_book(bid)
    return {"ok": True}


@app.post("/api/books/{bid}/activate")
def book_activate(bid: int):
    db.set_setting("active_book", bid)
    library.analyse_book(bid)
    return {"ok": True}


@app.get("/api/chapters/{cid}")
def chapter_get(cid: int, start: int = 0, length: int | None = None):
    ch = library.get_chapter(cid, start, length)
    if not ch:
        raise HTTPException(404, "No such chapter")
    return ch


class ChapterProgress(BaseModel):
    end: int
    seconds: int = 0


@app.post("/api/chapters/{cid}/progress")
def chapter_progress(cid: int, body: ChapterProgress):
    library.mark_read(cid, body.end)
    if body.seconds:
        db.log_activity("book", body.seconds, {"chapter": cid})
    return {"ok": True}


@app.get("/api/book/words")
def book_words(limit: int = 200):
    """Vocabulary still to learn for the novel: the companion pack plus words mined from the text."""
    have = {r["key"] for r in db.q("SELECT key FROM cards WHERE kind='word'")}
    pack = content_store.book_pack().get("vocab", [])
    items = []
    for x in pack:
        syls = (x.get("pinyin") or "").split()
        items.append({**x, "zhuyin": " ".join(pinyin_to_zhuyin(s) for s in syls), "learning": x["trad"] in have})
    mined = [w for w in (db.get_setting("book_words", []) or []) if w not in have][:limit]
    return {"pack": items, "mined": [decks._brief(w) for w in mined], "mined_total": len(db.get_setting("book_words", []) or [])}


# ----------------------------------------------------------------------------------------------
# Tutor
# ----------------------------------------------------------------------------------------------

@app.get("/api/tutor/scenarios")
def tutor_scenarios():
    week = curriculum.position(max(lessons.current_day(), 1))["info"]
    return {"scenarios": tutor.scenario_list(), "this_week": week.get("scenario_ids", []), "history": tutor.history(12)}


class TutorStart(BaseModel):
    scenario_id: str | None = None
    twist: bool = False
    topic: str = ""


@app.post("/api/tutor/start")
def tutor_start(body: TutorStart):
    return tutor.start(body.scenario_id, body.twist, body.topic)


@app.post("/api/tutor/{cid}/turn")
async def tutor_turn(cid: int, audio: UploadFile | None = File(None), text_: str = Form("", alias="text")):
    data = await audio.read() if audio is not None else None

    def gen():
        try:
            for ev in tutor.turn(cid, data, text_):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except KeyError:
            yield json.dumps({"type": "error", "message": "Conversation not found."}) + "\n"
        except Exception as e:  # noqa: BLE001
            log.exception("tutor turn failed")
            yield json.dumps({"type": "error", "message": str(e)[:200]}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/tutor/{cid}/hint")
def tutor_hint(cid: int):
    try:
        return tutor.hint(cid)
    except KeyError:
        raise HTTPException(404, "Conversation not found")


@app.post("/api/tutor/{cid}/finish")
def tutor_finish(cid: int):
    try:
        return tutor.finish(cid)
    except KeyError:
        raise HTTPException(404, "Conversation not found")


class Phrase(BaseModel):
    zh: str
    en: str = ""


@app.post("/api/srs/sentence")
def srs_sentence(body: Phrase):
    return {"id": decks.add_sentence_card(body.zh, body.en, source="tutor")}


# ----------------------------------------------------------------------------------------------
# Progress
# ----------------------------------------------------------------------------------------------

@app.get("/api/progress")
def progress():
    since = (date.today() - timedelta(days=83)).isoformat()
    act = db.q("SELECT day, kind, sum(seconds) s FROM activity WHERE day>=? GROUP BY day, kind", (since,))
    by_day: dict[str, dict] = {}
    for a in act:
        d = by_day.setdefault(a["day"], {"day": a["day"], "seconds": 0, "kinds": {}})
        d["seconds"] += a["s"] or 0
        d["kinds"][a["kind"]] = a["s"] or 0
    typing = db.q("SELECT date(ts) day, sum(chars) chars, sum(seconds) seconds, avg(accuracy) accuracy FROM typing_stats "
                  "WHERE seconds>3 GROUP BY date(ts) ORDER BY day")
    for t in typing:
        t["cpm"] = round(t["chars"] / t["seconds"] * 60, 1) if t["seconds"] else 0
    reviews = db.q("SELECT date(ts) day, count(*) n, avg(grade>1) ok FROM reviews GROUP BY date(ts) ORDER BY day DESC LIMIT 60")
    total = db.q1("SELECT coalesce(sum(seconds),0) s FROM activity")["s"]
    return {"summary": lessons.summary(), "decks": decks.deck_stats(), "days": sorted(by_day.values(), key=lambda d: d["day"]),
            "typing": typing, "reviews": list(reversed(reviews)), "srs": srs.counts(), "total_hours": round(total / 3600, 1),
            "book": _book_state(),
            "videos_watched": db.q1("SELECT count(*) n FROM videos WHERE watched_at IS NOT NULL")["n"],
            "conversations": db.q1("SELECT count(*) n FROM conversations")["n"],
            "known_words": db.q1("SELECT count(*) n FROM words WHERE status='known'")["n"]}


@app.get("/api/random-sentence")
def random_sentence():
    zh, en = random.choice(zhuyin_course.BASE_SENTENCES)
    return {"zh": zh, "en": en, "tokens": text.annotate(zh, False)}


# ----------------------------------------------------------------------------------------------
# Static files (built web app) and local media
# ----------------------------------------------------------------------------------------------

app.mount("/media", StaticFiles(directory=config.MEDIA_DIR), name="media")

if config.WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")


@app.exception_handler(Exception)
async def unhandled(request, exc):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": str(exc)[:300]}, status_code=500)


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    f = config.WEB_DIST / path
    if path and f.is_file():
        return FileResponse(f)
    index = config.WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "The web app has not been built yet. Run `npm run build` in web/."}, status_code=503)
