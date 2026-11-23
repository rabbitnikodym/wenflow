"""Loads the curated JSON content shipped in wenflow/content/."""
from __future__ import annotations

import json
from typing import Any

from .config import CONTENT_DIR

_cache: dict[str, tuple[float, Any]] = {}

# Everyday Taiwan spellings. Converters and dictionaries prefer the left-hand forms, but books, signs and
# chats in Taiwan overwhelmingly use the right-hand ones, so curated content is normalised on load.
_VARIANTS = str.maketrans({"臺": "台", "喫": "吃", "纔": "才", "牀": "床", "羣": "群", "癡": "痴", "裏": "裡", "爲": "為",
                           "麪": "麵", "着": "著"})
_KEEP_VARIANTS = {"s2t_bridge.json"}  # this file is about the variants themselves


def load_json(name: str, default: Any = None) -> Any:
    """Load a content file, re-reading it if it changed on disk (content can be regenerated)."""
    p = CONTENT_DIR / name
    if not p.exists():
        return default
    mtime = p.stat().st_mtime
    hit = _cache.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(p, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return default
    if name not in _KEEP_VARIANTS:
        raw = raw.translate(_VARIANTS)
    try:
        v = json.loads(raw)
    except json.JSONDecodeError:
        return default
    _cache[name] = (mtime, v)
    return v


_TW_FILES = ("taiwan_vocab.json", "taiwan_vocab_a.json", "taiwan_vocab_b.json")
_tw: dict[str, Any] = {"sig": None, "list": [], "index": {}}


def _tw_load() -> dict[str, Any]:
    sig = tuple((CONTENT_DIR / n).stat().st_mtime if (CONTENT_DIR / n).exists() else 0 for n in _TW_FILES)
    if sig != _tw["sig"]:
        out, seen = [], set()
        for name in _TW_FILES:
            for item in load_json(name, []) or []:
                w = item.get("trad")
                if not w or w in seen:
                    continue
                seen.add(w)
                if "level" not in item:  # older files grade by 'stage' 1-5
                    item["level"] = {1: 1, 2: 1, 3: 2, 4: 3, 5: 3}.get(item.get("stage", 3), 2)
                if item.get("register") == "casual":
                    item["register"] = "colloquial"
                out.append(item)
        out.sort(key=lambda x: x.get("level", 2))  # stable: keeps file order within a level
        _tw.update(sig=sig, list=out, index={x["trad"]: x for x in out})
    return _tw


def taiwan_vocab() -> list[dict]:
    """Curated Taiwan vocabulary: part files merged and de-duplicated."""
    return _tw_load()["list"]


def taiwan_vocab_index() -> dict[str, dict]:
    return _tw_load()["index"]


def scenarios() -> list[dict]:
    return load_json("scenarios.json", [])


def scenario(sid: str) -> dict | None:
    return next((s for s in scenarios() if s["id"] == sid), None)


def grammar_points() -> list[dict]:
    return load_json("grammar_points.json", [])


def s2t_bridge() -> dict:
    return load_json("s2t_bridge.json", {}) or {}


def pronunciation_diffs() -> list[dict]:
    return load_json("pronunciation_diffs.json", [])


def book_pack(book_id: str = "nxn") -> dict:
    return load_json(f"book_{book_id}.json", {}) or {}


def video_sources() -> dict:
    return load_json("video_sources.json", {}) or {}


def reading_sources() -> dict:
    return load_json("reading_sources.json", {}) or {}
