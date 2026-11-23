"""The local Taiwanese-Mandarin voice (BreezyVoice): process manager and client.

The model lives in its own environment (data/voice/, installed by server/voice/install.sh) and is
served by server/voice/worker.py on localhost. This module starts that worker when the voice is
needed, talks to it, and prepares text so the voice uses the same Taiwan readings the app displays.
"""
from __future__ import annotations

import atexit
import logging
import os
import re
import subprocess
import threading
import time

import httpx

from . import config

log = logging.getLogger("wenflow.voice")

VOICE_ID = "local-breezy"
VOICE_LABEL = "BreezyVoice 台灣腔 (local, on your GPU)"
PORT = int(os.getenv("WENFLOW_VOICE_PORT", "8011"))
URL = f"http://127.0.0.1:{PORT}"
VOICE_DIR = config.DATA_DIR / "voice"
PYTHON = VOICE_DIR / "venv" / "bin" / "python"
WORKER = config.ROOT / "server" / "voice" / "worker.py"
LOG = VOICE_DIR / "worker.log"

_proc: subprocess.Popen | None = None
_lock = threading.Lock()
_started_at = 0.0
_HAN = re.compile(r"[㐀-鿿]")


def installed() -> bool:
    return PYTHON.exists() and (VOICE_DIR / "BreezyVoice" / "single_inference.py").exists() and WORKER.exists()


def _health(timeout: float = 1.0) -> dict | None:
    try:
        r = httpx.get(f"{URL}/health", timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001 - not running
        return None


def status() -> dict:
    if not installed():
        return {"installed": False, "ready": False, "state": "not installed"}
    h = _health(0.5)
    if h and h.get("ready"):
        return {"installed": True, "ready": True, "state": "ready", "device": h.get("device")}
    if h and h.get("error"):
        return {"installed": True, "ready": False, "state": "failed", "error": h["error"]}
    running = _proc is not None and _proc.poll() is None
    return {"installed": True, "ready": False, "state": "loading" if (h or running) else "stopped"}


def start() -> bool:
    """Start the worker if it is not already running. Returns False when it is not installed."""
    global _proc, _started_at
    if not installed():
        return False
    with _lock:
        if _health(0.5) is not None or (_proc is not None and _proc.poll() is None):
            return True
        env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        env.pop("PYTHONPATH", None)
        out = open(LOG, "ab")
        _proc = subprocess.Popen([str(PYTHON), str(WORKER), "--port", str(PORT), "--fp16", "--parent", str(os.getpid())],
                                 stdout=out, stderr=subprocess.STDOUT, env=env, cwd=str(config.ROOT))
        _started_at = time.time()
        log.info("local voice worker starting (pid %s)", _proc.pid)
        return True


def wait_ready(timeout: float = 120.0) -> bool:
    if not start():
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        h = _health(1.0)
        if h and h.get("ready"):
            return True
        if h and h.get("error"):
            return False
        if _proc is not None and _proc.poll() is not None:
            return False
        time.sleep(1.0)
    return False


@atexit.register
def stop() -> None:
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


def synth(annotated: str, seed: int = 0, timeout: float = 90.0) -> bytes:
    """WAV bytes for text that may carry [:zhuyin] readings. Raises if the worker is unavailable."""
    r = httpx.post(f"{URL}/tts", json={"text": annotated, "seed": seed}, timeout=timeout)
    r.raise_for_status()
    return r.content


def annotate(text: str) -> str:
    """Mark the readings this app uses wherever the voice might otherwise choose differently.

    The voice does its own polyphone disambiguation and was trained mostly on mainland speech, so a
    mark is added wherever the Taiwan reading shown in the app differs from the mainland default
    (星期 qí, 企業 qì, 東西 with a full tone) or from the reading model's raw guess. Marks nudge the
    voice rather than force it — clips are verified afterwards — and are kept sparse, which is how
    the model was trained to receive them.
    """
    from . import g2p
    from . import text as textmod
    from .zhuyin import pinyin_to_zhuyin

    if "[:" in text or not _HAN.search(text):
        return text
    raw = g2p.readings(text) or [None] * len(text)
    out = []
    pos = 0
    for tok in textmod.annotate(text, with_gloss=False):
        w = tok["w"]
        if not tok["han"]:
            out.append(w)
            pos += len(w)
            continue
        mainland = textmod._dict_reading(w)
        for i, ch in enumerate(tok["chars"]):
            out.append(ch["c"])
            zy = ch.get("zy")
            if not zy:
                continue
            guess = raw[pos + i] if pos + i < len(raw) else None
            differs = (guess is not None and pinyin_to_zhuyin(guess) != zy) or \
                      (i < len(mainland) and mainland[i] != "?" and pinyin_to_zhuyin(mainland[i]) != zy
                       and ch["c"] not in "一不")
            if differs:
                out.append(f"[:{re.sub(r'[ˊˇˋ˙]', '', zy)}{ch['t']}]")
        pos += len(w)
    return "".join(out)
