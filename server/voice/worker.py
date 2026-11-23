"""Local Taiwanese-Mandarin voice worker (MediaTek Research BreezyVoice).

Runs in its own environment (data/voice/venv) and serves the main app over localhost:

    data/voice/venv/bin/python server/voice/worker.py --port 8011

POST /tts {"text": "...", "seed": 0}  ->  WAV bytes (22.05 kHz mono)
    `text` may carry readings as 字[:ㄓㄨˋ-style zhuyin + tone digit], e.g. 垃[:ㄌㄜ4]圾[:ㄙㄜ4].
GET  /health                          ->  {"ready": true, "device": "cuda", ...}

The model clones the voice of a short reference recording. The speaker's features are computed once
at start-up; each request then only encodes the new text.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "data" / "voice" / "BreezyVoice"
os.environ.setdefault("PYTHONUTF8", "1")
os.chdir(REPO)  # the model code resolves a few paths relative to its own folder
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "third_party" / "Matcha-TTS"))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

SR = 22050
DEFAULT_PROMPT_TEXT = ("在密碼學中，加密是將明文資訊改變為難以讀取的密文內容，使之不可讀的方法。"
                       "只有擁有解密方法的對象，經由解密過程，才能將密文還原為正常可讀的內容。")

app = FastAPI(title="Wenflow voice worker")
_lock = threading.Lock()
state: dict = {"ready": False, "error": None, "loaded_in": None}


def load(model_path: str, prompt_wav: str, prompt_text: str, g2p_dir: str | None) -> None:
    t0 = time.time()
    from g2pw import G2PWConverter
    from single_inference import CustomCosyVoice, get_bopomofo_rare

    from cosyvoice.utils.file_utils import load_wav

    import opencc
    from tn.chinese.normalizer import Normalizer as ZhNormalizer

    cosy = CustomCosyVoice(model_path)
    # The stock fallback normaliser converts Traditional to Simplified and full-width punctuation to
    # half-width, which the Taiwan-trained model then mis-reads. Build one that leaves both alone.
    cache = ROOT / "data" / "voice" / "tn_cache"
    cache.mkdir(exist_ok=True)
    state["zh_tn"] = ZhNormalizer(cache_dir=str(cache), overwrite_cache=not (cache / "zh_tn_tagger.fst").exists(),
                                  remove_interjections=False, remove_erhua=False, traditional_to_simple=False,
                                  full_to_half=False)
    state["s2tw"] = opencc.OpenCC("s2tw")
    g2p = G2PWConverter(model_dir=g2p_dir) if g2p_dir else G2PWConverter()
    g2p.num_workers = 0  # no forked data-loader workers next to a CUDA context
    prompt_16k = load_wav(prompt_wav, 16000)
    ptext = get_bopomofo_rare(cosy.frontend.text_normalize_new(prompt_text, split=False), g2p)
    # Everything that depends only on the speaker, computed once.
    base = cosy.frontend.frontend_zero_shot("好。", ptext, prompt_16k)
    speaker = {k: v for k, v in base.items() if k not in ("text", "text_len")}
    state.update(cosy=cosy, g2p=g2p, annotate=get_bopomofo_rare, speaker=speaker, ready=True,
                 device=str(cosy.model.device), loaded_in=round(time.time() - t0, 1))


_MARK = re.compile(r"(\[:[^\]]*\])")


def normalize(text: str) -> str:
    """Expand numbers and tidy punctuation, leaving [:reading] marks attached to their characters.

    (The upstream helper assumes a text front end that appends a full stop to each piece and strips
    one character to compensate; with the open-source normaliser used here that would delete the
    character a mark belongs to, so the pieces are normalised here instead.)"""
    from cosyvoice.utils.frontend_utils import contains_chinese, replace_blank, replace_corner_mark

    out = []
    for part in _MARK.split(text.strip()):
        if not part:
            continue
        if part.startswith("[:"):
            out.append(part)
            continue
        if contains_chinese(part):
            part = state["zh_tn"].normalize(part).replace("\n", "")
            part = state["s2tw"].convert(part)  # number words come out Simplified (万, 两)
            part = replace_corner_mark(replace_blank(part)).replace(" - ", "，")
        out.append(part)
    res = re.sub(r"[，,、]+$", "", "".join(out))
    if res and res[-1] not in "。！？!?":
        res += "。"
    return res


def synthesize(text: str, seed: int) -> np.ndarray:
    cosy, g2p = state["cosy"], state["g2p"]
    norm = normalize(text)
    annotated = state["annotate"](norm, g2p)
    pieces = []
    for i, sentence in enumerate(s for s in re.split(r"(?<=[？！。.?!])\s*", annotated) if s):
        torch.manual_seed(seed + i)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed + i)
        tok, tok_len = cosy.frontend._extract_text_token(sentence)
        out = cosy.model.inference(text=tok, text_len=tok_len, **state["speaker"])
        pieces.append(out["tts_speech"].squeeze(0).float().cpu().numpy())
    if not pieces:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(pieces)


def to_wav(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


class TtsIn(BaseModel):
    text: str
    seed: int = 0


@app.get("/health")
def health():
    return {k: state.get(k) for k in ("ready", "error", "device", "loaded_in")}


@app.post("/tts")
def tts(body: TtsIn):
    if not state["ready"]:
        raise HTTPException(503, state["error"] or "model is still loading")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "text required")
    with _lock:
        t0 = time.time()
        try:
            with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16, enabled=state.get("fp16", False)):
                samples = synthesize(text, body.seed)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"synthesis failed: {e}")
        took = time.time() - t0
    return Response(to_wav(samples), media_type="audio/wav",
                    headers={"X-Seconds": f"{took:.2f}", "X-Audio-Seconds": f"{len(samples) / SR:.2f}"})


class TextIn(BaseModel):
    text: str


@app.post("/prepare")
def prepare(body: TextIn):
    """What the model is actually given for a text (after normalisation and automatic readings)."""
    if not state["ready"]:
        raise HTTPException(503, "model is still loading")
    return {"text": state["annotate"](normalize(body.text), state["g2p"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--model", default="MediaTek-Research/BreezyVoice-300M")
    ap.add_argument("--prompt-wav", default=str(REPO / "data" / "example.wav"))
    ap.add_argument("--prompt-text", default=DEFAULT_PROMPT_TEXT)
    ap.add_argument("--g2p-dir", default=str(ROOT / "data" / "models" / "G2PWModel") + "/")
    ap.add_argument("--fp16", action="store_true", help="half precision on the GPU (faster, slightly less stable)")
    ap.add_argument("--parent", type=int, default=0, help="exit when this process (the app) is gone")
    args = ap.parse_args()
    if args.parent:
        def watch():  # never outlive the app that started us, however it was stopped
            while True:
                time.sleep(2)
                if os.getppid() != args.parent:
                    os._exit(0)

        threading.Thread(target=watch, daemon=True).start()
    state["fp16"] = args.fp16 and torch.cuda.is_available()

    def boot():
        try:
            load(args.model, args.prompt_wav, args.prompt_text, args.g2p_dir if Path(args.g2p_dir).exists() else None)
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            state["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=boot, daemon=True).start()
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
