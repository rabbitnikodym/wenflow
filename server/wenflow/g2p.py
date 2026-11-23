"""Context-aware readings for running text using g2pW, a polyphone model trained on Taiwan Mandarin.

`readings(sentence)` returns numbered pinyin per character ('chang2', None for non-Han). Results are
cached on disk because the model costs a few milliseconds per polyphonic character.
If the model cannot be loaded the caller falls back to dictionary-based readings.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading

from . import config

log = logging.getLogger("wenflow.g2p")
MODEL_DIR = config.DATA_DIR / "models" / "G2PWModel"
CACHE_DB = config.DATA_DIR / "cache.sqlite"

_conv = None
_failed = False
_lock = threading.Lock()
_infer_lock = threading.Lock()
_local = threading.local()
_bpmf2py: dict[str, str] = {}
_mem: dict[str, list[str | None]] = {}

SPLIT_RE = re.compile(r"(?<=[。！？!?；;\n…])")


def _cache() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(CACHE_DB, timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE IF NOT EXISTS g2p(text TEXT PRIMARY KEY, py TEXT)")
        _local.c = c
    return c


def load() -> bool:
    """Load the model (downloads ~600 MB on first use). Returns False if unavailable."""
    global _conv, _failed
    if _conv is not None:
        return True
    if _failed:
        return False
    with _lock:
        if _conv is not None:
            return True
        if _failed:
            return False
        try:
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            import g2pw
            import onnxruntime
            from g2pw import G2PWConverter

            MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
            conv = G2PWConverter(model_dir=str(MODEL_DIR) + "/", style="bopomofo", batch_size=64)
            # The library treats num_workers=0 as "use the default (2)". Worker processes are forked, and
            # forking a process that already holds a CUDA context (Whisper) deadlocks — so force in-process.
            conv.num_workers = 0
            # The stock session uses 2 threads; this machine has many more.
            so = onnxruntime.SessionOptions()
            so.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
            so.intra_op_num_threads = max(2, min(12, (os.cpu_count() or 4) // 2))
            conv.session_g2pw = onnxruntime.InferenceSession(str(MODEL_DIR / "g2pw.onnx"), sess_options=so,
                                                            providers=["CPUExecutionProvider"])
            with open(os.path.join(os.path.dirname(g2pw.__file__), "bopomofo_to_pinyin_wo_tune_dict.json"), encoding="utf-8") as f:
                _bpmf2py.update({k: v for k, v in json.load(f).items() if v})
            _conv = conv
            log.info("g2pW loaded")
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("g2pW unavailable, using dictionary readings: %s", e)
            _failed = True
            return False


def status() -> dict:
    return {"loaded": _conv is not None, "failed": _failed}


def _to_py(b: str | None) -> str | None:
    if not b:
        return None
    body, tone = b[:-1], b[-1]
    py = _bpmf2py.get(body)
    if not py or tone not in "12345":
        return None
    return py.replace("v", "ü") + tone


def _chunks(text: str, limit: int = 60) -> list[str]:
    """Sentence-sized pieces whose concatenation is the original text."""
    out = []
    for part in SPLIT_RE.split(text):
        while len(part) > limit:
            cut = max(part.rfind("，", 0, limit), part.rfind(",", 0, limit), part.rfind("、", 0, limit))
            cut = cut + 1 if cut > 10 else limit
            out.append(part[:cut])
            part = part[cut:]
        if part:
            out.append(part)
    return out


def readings_many(texts: list[str]) -> list[list[str | None]] | None:
    """Numbered pinyin per character for each text, or None if the model is unavailable."""
    if not load():
        return None
    pieces: list[list[str]] = [_chunks(t) for t in texts]
    need = []
    for ps in pieces:
        for p in ps:
            if p not in _mem and p not in need:
                need.append(p)
    if need:
        db = _cache()
        todo = []
        for i in range(0, len(need), 400):
            batch = need[i:i + 400]
            rows = db.execute(f"SELECT text, py FROM g2p WHERE text IN ({','.join('?' * len(batch))})", batch).fetchall()
            got = {t: json.loads(p) for t, p in rows}
            for p in batch:
                if p in got:
                    _mem[p] = got[p]
                else:
                    todo.append(p)
        if todo:
            with _infer_lock:
                try:
                    res = _conv(todo)
                except Exception as e:  # noqa: BLE001
                    log.warning("g2pW inference failed: %s", e)
                    return None
            rows = []
            for p, r in zip(todo, res):
                pys = [_to_py(x) for x in r]
                _mem[p] = pys
                rows.append((p, json.dumps(pys, ensure_ascii=False)))
            db.executemany("INSERT OR REPLACE INTO g2p(text,py) VALUES(?,?)", rows)
            db.commit()
        if len(_mem) > 60000:
            for k in list(_mem)[:20000]:
                _mem.pop(k, None)
    out = []
    for ps in pieces:
        row: list[str | None] = []
        for p in ps:
            row.extend(_mem.get(p) or [None] * len(p))
        out.append(row)
    return out


def readings(text: str) -> list[str | None] | None:
    r = readings_many([text])
    return r[0] if r else None
