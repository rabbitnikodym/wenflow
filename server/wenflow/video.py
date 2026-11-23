"""Videos: import from YouTube (or a local file), get time-coded captions, grade the difficulty,
and find new Taiwanese videos at the learner's level every day.

Captions come from the video's own Chinese subtitle track when it has one; otherwise the audio is
transcribed locally with Whisper.
"""
from __future__ import annotations

import json
import logging
import random
import re
import shutil
import threading
import time
from pathlib import Path

import httpx

from . import config, content_store, curriculum, db, text

log = logging.getLogger("wenflow.video")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
ZH_MANUAL = ["zh-TW", "zh-Hant", "zh-Hant-TW", "zh-HK", "zh", "zh-Hans", "zh-CN", "zh-Hans-CN", "zh-SG"]
YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")

_jobs: dict[str, dict] = {}
_job_lock = threading.Lock()
_work_lock = threading.Lock()  # one heavy job (download + Whisper) at a time


def _node() -> str | None:
    for cand in (shutil.which("node"), str(Path.home() / ".local/bin/node"), "/usr/bin/node", "/usr/local/bin/node"):
        if cand and Path(cand).exists():
            return cand
    return None


def ydl_opts(**extra) -> dict:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noprogress": True, "socket_timeout": 20,
            "extractor_retries": 1, "retries": 2}
    node = _node()
    if node:
        opts["js_runtimes"] = {"node": {"path": node}}
    opts.update(extra)
    return opts


def youtube_id(url: str) -> str | None:
    m = YT_ID_RE.search(url)
    if m:
        return m.group(1)
    return url if re.fullmatch(r"[A-Za-z0-9_-]{11}", url.strip()) else None


def fetch_info(url: str) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL(ydl_opts()) as y:
        return y.extract_info(url, download=False)


# ----------------------------------------------------------------------------------------------
# Captions
# ----------------------------------------------------------------------------------------------

def _pick_track(info: dict) -> tuple[str, str, str] | None:
    """(url, ext, source) of the best Chinese caption track: human-made first, then auto-generated."""
    subs = info.get("subtitles") or {}
    for lang in ZH_MANUAL + [k for k in subs if k.lower().startswith("zh")]:
        if lang in subs:
            for ext in ("json3", "vtt", "srv1"):
                f = next((x for x in subs[lang] if x.get("ext") == ext and x.get("url")), None)
                if f:
                    return f["url"], ext, "subtitles"
    auto = info.get("automatic_captions") or {}
    # Only use auto captions when the spoken language itself is Chinese (not a machine translation).
    orig = [k for k in auto if k.lower().startswith("zh") and k.endswith("-orig")] or \
           ([k for k in ("zh-Hant", "zh-TW", "zh", "zh-Hans") if k in auto] if (info.get("language") or "").startswith("zh") else [])
    for lang in orig:
        for ext in ("json3", "vtt"):
            f = next((x for x in auto[lang] if x.get("ext") == ext and x.get("url")), None)
            if f:
                return f["url"], ext, "auto"
    return None


def _parse_json3(data: dict) -> list[dict]:
    out = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        t = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if not t:
            continue
        start = ev.get("tStartMs", 0) / 1000
        out.append({"s": start, "e": start + (ev.get("dDurationMs") or 2000) / 1000, "t": t})
    return out


def _parse_vtt(body: str) -> list[dict]:
    out = []
    ts = re.compile(r"(\d+):(\d\d):(\d\d)[.,](\d{3})\s*-->\s*(\d+):(\d\d):(\d\d)[.,](\d{3})")
    cur = None
    for line in body.splitlines():
        m = ts.search(line)
        if m:
            g = [int(x) for x in m.groups()]
            cur = {"s": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, "e": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, "t": ""}
            out.append(cur)
        elif cur is not None and line.strip() and not line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            cur["t"] = (cur["t"] + " " + re.sub(r"<[^>]+>", "", line).strip()).strip()
        elif not line.strip():
            cur = None
    return [c for c in out if c["t"]]


def _tidy(caps: list[dict]) -> list[dict]:
    """Traditional characters, no duplicates or overlaps, lines of a readable length."""
    if not caps:
        return []
    simp = text.is_simplified("".join(c["t"] for c in caps[:200]))
    out: list[dict] = []
    for c in sorted(caps, key=lambda c: c["s"]):
        t = re.sub(r"\s+", " ", c["t"]).strip()
        t = re.sub(r"^[\-–—>\s]+", "", t)
        if simp:
            t = text.to_traditional(t)
        t = text.fullwidth_punct(t)
        if not t or not text.HAN_RE.search(t):
            continue
        if out and (t == out[-1]["t"] or t in out[-1]["t"]):
            out[-1]["e"] = max(out[-1]["e"], c["e"])
            continue
        if out and out[-1]["t"] and t.startswith(out[-1]["t"]) and c["s"] - out[-1]["s"] < 4:
            out[-1] = {"s": out[-1]["s"], "e": c["e"], "t": t}  # rolling auto-caption: keep the longer line
            continue
        out.append({"s": round(c["s"], 2), "e": round(c["e"], 2), "t": t})
    for a, b in zip(out, out[1:]):
        if a["e"] > b["s"]:
            a["e"] = b["s"]
    return out


def fetch_track(url: str, ext: str) -> list[dict]:
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return _parse_json3(r.json()) if ext == "json3" else _parse_vtt(r.text)


def download_audio(url: str, vid: str) -> Path:
    import yt_dlp

    for old in config.MEDIA_DIR.glob(f"{vid}.audio.*"):
        return old
    opts = ydl_opts(skip_download=False, format="bestaudio[abr<=96]/bestaudio/best[height<=360]/best",
                    outtmpl=str(config.MEDIA_DIR / f"{vid}.audio.%(ext)s"))
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([url])
    files = list(config.MEDIA_DIR.glob(f"{vid}.audio.*"))
    if not files:
        raise RuntimeError("audio download produced no file")
    return files[0]


def whisper_captions(path: Path, progress=None) -> list[dict]:
    from . import speech

    audio = speech.decode_audio(path.read_bytes())
    res = speech.transcribe(audio, word_timestamps=False)
    return [{"s": s["start"], "e": s["end"], "t": s["text"]} for s in res["segments"] if s["text"].strip()]


def split_long(caps: list[dict], max_chars: int = 26) -> list[dict]:
    """Break long transcript segments at punctuation so each caption is one readable line."""
    out = []
    for c in caps:
        t = c["t"]
        if len(t) <= max_chars:
            out.append(c)
            continue
        parts = [p for p in re.split(r"(?<=[，。！？、,.!?；;])", t) if p.strip()]
        merged: list[str] = []
        for p in parts:
            if merged and len(merged[-1]) + len(p) <= max_chars:
                merged[-1] += p
            else:
                merged.append(p)
        total = sum(len(p) for p in merged) or 1
        s = c["s"]
        for p in merged:
            d = (c["e"] - c["s"]) * len(p) / total
            out.append({"s": round(s, 2), "e": round(s + d, 2), "t": p.strip()})
            s += d
    return out


# ----------------------------------------------------------------------------------------------
# Import pipeline
# ----------------------------------------------------------------------------------------------

def _set(job_id: str, **kw) -> None:
    with _job_lock:
        _jobs.setdefault(job_id, {}).update(kw)


def job(job_id: str) -> dict:
    with _job_lock:
        return dict(_jobs.get(job_id, {"state": "unknown"}))


def grade(caps: list[dict]) -> dict:
    words: list[str] = []
    for c in caps:
        words += text.segment(c["t"])
    d = text.word_difficulty(words, db.known_words())
    han = sum(len(text.HAN_RE.findall(c["t"])) for c in caps)
    dur = (caps[-1]["e"] - caps[0]["s"]) if caps else 0
    d["cpm"] = round(han / dur * 60) if dur > 5 else 0  # speaking rate, characters per minute
    return d


def upsert_meta(info: dict, source: str, status: str = "new", recommended_on: str | None = None,
                level: int | None = None, meta: dict | None = None) -> str:
    vid = info["id"]
    thumb = info.get("thumbnail") or f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
    row = db.q1("SELECT id, status FROM videos WHERE id=?", (vid,))
    if row:
        if recommended_on:
            db.ex("UPDATE videos SET recommended_on=coalesce(recommended_on, ?) WHERE id=?", (recommended_on, vid))
        return vid
    db.ex("INSERT INTO videos(id,title,channel,url,duration,thumbnail,source,level,status,recommended_on,added_at,meta) "
          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
          (vid, info.get("title", ""), info.get("channel") or info.get("uploader") or "",
           info.get("webpage_url") or info.get("url") or f"https://www.youtube.com/watch?v={vid}",
           info.get("duration") or 0, thumb, source, level, status, recommended_on, db.now(),
           json.dumps(meta or {}, ensure_ascii=False)))
    return vid


def start_import(url: str) -> dict:
    """Begin importing a YouTube URL. Returns {video_id, job}; poll job() until state is 'ready'."""
    vid = youtube_id(url)
    if not vid:
        raise ValueError("That does not look like a YouTube link.")
    row = db.q1("SELECT id, captions FROM videos WHERE id=?", (vid,))
    if row and row["captions"]:
        return {"video_id": vid, "job": None, "state": "ready"}
    cur = job(vid)
    if cur.get("state") in ("queued", "working"):
        return {"video_id": vid, "job": vid, "state": cur["state"]}
    _set(vid, state="queued", step="Queued", error=None)
    threading.Thread(target=_run_import, args=(vid,), daemon=True).start()
    return {"video_id": vid, "job": vid, "state": "queued"}


def _run_import(vid: str) -> None:
    url = f"https://www.youtube.com/watch?v={vid}"
    try:
        _set(vid, state="working", step="Reading video details")
        info = fetch_info(url)
        upsert_meta(info, source="youtube")
        db.ex("UPDATE videos SET title=?, channel=?, duration=?, status=CASE WHEN status='suggested' THEN 'suggested' ELSE status END WHERE id=?",
              (info.get("title", ""), info.get("channel") or info.get("uploader") or "", info.get("duration") or 0, vid))
        caps, source = [], ""
        track = _pick_track(info)
        if track:
            _set(vid, step="Downloading captions")
            try:
                caps = _tidy(fetch_track(track[0], track[1]))
                source = track[2]
            except Exception as e:  # noqa: BLE001
                log.info("caption track failed for %s: %s", vid, e)
        if len(caps) < 5:
            if (info.get("duration") or 0) > 75 * 60:
                raise RuntimeError("No Chinese captions, and the video is too long to transcribe (over 75 minutes).")
            with _work_lock:
                _set(vid, step="No caption track — downloading audio")
                path = download_audio(url, vid)
                _set(vid, step="Transcribing with Whisper")
                caps = _tidy(split_long(whisper_captions(path)))
                source = "whisper"
                try:
                    path.unlink()
                except OSError:
                    pass
        else:
            caps = split_long(caps, 40)
        if not caps:
            raise RuntimeError("No speech could be transcribed from this video.")
        _set(vid, step="Annotating")
        text.annotate_many([c["t"] for c in caps])  # warm the reading cache
        g = grade(caps)
        db.ex("UPDATE videos SET captions=?, caption_source=?, coverage=?, level=?, meta=? WHERE id=?",
              (json.dumps(caps, ensure_ascii=False), source, g["coverage"], g["level"],
               json.dumps({"unknown": g["unknown"][:120], "cpm": g["cpm"]}, ensure_ascii=False), vid))
        _set(vid, state="ready", step="Ready")
    except Exception as e:  # noqa: BLE001
        log.warning("import %s failed: %s", vid, e)
        msg = str(e)
        msg = re.sub(r"^ERROR: \[youtube\] [\w-]+: ", "", msg)
        _set(vid, state="error", error=msg[:300], step="Failed")


def import_local(filename: str, data: bytes) -> dict:
    """A video or audio file from disk: stored under data/media and transcribed with Whisper."""
    import hashlib

    vid = "local-" + hashlib.sha1(data[:2_000_000] + str(len(data)).encode()).hexdigest()[:12]
    ext = Path(filename).suffix.lower() or ".mp4"
    path = config.MEDIA_DIR / f"{vid}{ext}"
    if not path.exists():
        path.write_bytes(data)
    if not db.q1("SELECT id FROM videos WHERE id=?", (vid,)):
        db.ex("INSERT INTO videos(id,title,channel,url,duration,thumbnail,source,status,added_at,meta) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (vid, Path(filename).stem, "Local file", f"/media/{vid}{ext}", 0, "", "local", "new", db.now(), "{}"))
    _set(vid, state="queued", step="Queued", error=None)

    def run():
        try:
            with _work_lock:
                _set(vid, state="working", step="Transcribing with Whisper")
                caps = _tidy(split_long(whisper_captions(path)))
            if not caps:
                raise RuntimeError("No speech found in this file.")
            text.annotate_many([c["t"] for c in caps])
            g = grade(caps)
            db.ex("UPDATE videos SET captions=?, caption_source='whisper', coverage=?, level=?, duration=?, meta=? WHERE id=?",
                  (json.dumps(caps, ensure_ascii=False), g["coverage"], g["level"], caps[-1]["e"],
                   json.dumps({"unknown": g["unknown"][:120], "cpm": g["cpm"]}, ensure_ascii=False), vid))
            _set(vid, state="ready", step="Ready")
        except Exception as e:  # noqa: BLE001
            _set(vid, state="error", error=str(e)[:300], step="Failed")

    threading.Thread(target=run, daemon=True).start()
    return {"video_id": vid, "job": vid, "state": "queued"}


def get(vid: str, annotate: bool = True) -> dict | None:
    r = db.q1("SELECT * FROM videos WHERE id=?", (vid,))
    if not r:
        return None
    r["meta"] = json.loads(r["meta"] or "{}")
    caps = json.loads(r["captions"] or "[]")
    if annotate and caps:
        toks = text.annotate_many([c["t"] for c in caps], with_gloss=True)
        for c, t in zip(caps, toks):
            c["tokens"] = t
    r["captions"] = caps
    r["job"] = job(vid) if vid in _jobs else None
    return r


def library() -> list[dict]:
    rows = db.q("SELECT id,title,channel,url,duration,thumbnail,source,caption_source,level,coverage,status,"
                "recommended_on,added_at,watched_at,meta, captions IS NOT NULL AND captions!='' ready "
                "FROM videos ORDER BY coalesce(watched_at, added_at) DESC")
    for r in rows:
        r["meta"] = json.loads(r["meta"] or "{}")
        j = job(r["id"]) if r["id"] in _jobs else None
        r["job"] = j
    return rows


def mark_watched(vid: str, seconds: int = 0) -> None:
    db.ex("UPDATE videos SET watched_at=?, status='watched' WHERE id=?", (db.now(), vid))
    if seconds:
        db.log_activity("video", seconds, {"video": vid})


def delete(vid: str) -> None:
    db.ex("DELETE FROM videos WHERE id=?", (vid,))
    for f in config.MEDIA_DIR.glob(f"{vid}*"):
        try:
            f.unlink()
        except OSError:
            pass


# ----------------------------------------------------------------------------------------------
# Daily discovery
# ----------------------------------------------------------------------------------------------

def target_level() -> int:
    """Channel difficulty (1-5) that suits the current point in the year."""
    from . import lessons

    week = curriculum.position(max(lessons.current_day(), 1))["week"]
    return 2 if week <= 4 else 3 if week <= 16 else 4 if week <= 36 else 5


def _flat(url: str, n: int) -> list[dict]:
    import yt_dlp

    with yt_dlp.YoutubeDL(ydl_opts(extract_flat=True, playlistend=n)) as y:
        info = y.extract_info(url, download=False)
    return [e for e in (info.get("entries") or []) if e and e.get("id")]


def discover(force: bool = False) -> list[dict]:
    """Pick today's handful of new videos from curated Taiwanese channels and themed searches."""
    today = db.today()
    have = db.q("SELECT id FROM videos WHERE recommended_on=?", (today,))
    if have and not force:
        return todays()
    src = content_store.video_sources()
    channels, queries = src.get("channels", []), src.get("queries", [])
    lvl = target_level()
    rng = random.Random(f"{today}-{len(have)}")
    near = [c for c in channels if abs(c.get("level", 3) - lvl) <= 1]
    rng.shuffle(near)
    picks: list[tuple[dict, dict]] = []
    seen = {r["id"] for r in db.q("SELECT id FROM videos")}
    deadline = time.time() + 45
    for ch in near[:7]:
        if time.time() > deadline or len(picks) >= 6:
            break
        handle = ch.get("handle") or ""
        url = f"https://www.youtube.com/{handle}/videos" if handle.startswith("@") else f"https://www.youtube.com/channel/{ch.get('channel_id')}/videos"
        try:
            entries = _flat(url, 8)
        except Exception as e:  # noqa: BLE001
            log.info("channel %s failed: %s", ch.get("name"), e)
            continue
        ok = [e for e in entries if e["id"] not in seen and 150 <= (e.get("duration") or 0) <= 1500]
        if ok:
            e = rng.choice(ok[:5])
            e["channel"] = ch.get("name")
            picks.append((e, ch))
            seen.add(e["id"])
    if len(picks) < 6 and queries:
        from . import lessons

        info = curriculum.position(max(lessons.current_day(), 1))["info"]
        qs = [q for q in queries if abs(q.get("level", 3) - lvl) <= 1]
        rng.shuffle(qs)
        theme_q = [{"q": f"台灣 {d}", "level": lvl, "category": "theme"} for d in (info.get("vocab_domains") or [])[:1]
                   if re.search(r"[一-鿿]", d)]
        for q in (theme_q + qs)[:3]:
            if time.time() > deadline or len(picks) >= 6:
                break
            try:
                entries = _flat(f"ytsearch8:{q['q']}", 8)
            except Exception:  # noqa: BLE001
                continue
            ok = [e for e in entries if e["id"] not in seen and 150 <= (e.get("duration") or 0) <= 1500
                  and text.HAN_RE.search(e.get("title") or "")]
            for e in ok[:2]:
                picks.append((e, {"level": q.get("level", lvl), "category": q.get("category", ""), "captions": "unknown"}))
                seen.add(e["id"])
    for e, ch in picks:
        upsert_meta(e, source="discover", status="suggested", recommended_on=today, level=None,
                    meta={"channel_level": ch.get("level"), "category": ch.get("category"), "captions_hint": ch.get("captions")})
    # Prepare the first two in the background so they open instantly and show a measured level.
    for e, _ in picks[:2]:
        try:
            start_import(e["id"])
        except Exception:  # noqa: BLE001
            pass
    return todays()


def todays() -> list[dict]:
    rows = [r for r in library() if r["recommended_on"] == db.today()]
    lvl = target_level()

    def fit(r):
        if r["coverage"] is not None:
            return abs(r["coverage"] - 0.93)
        return 0.05 + 0.03 * abs((r["meta"].get("channel_level") or 3) - lvl)

    return sorted(rows, key=fit)
