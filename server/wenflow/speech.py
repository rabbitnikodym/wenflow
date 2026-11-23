"""Speech: audio decoding, local Whisper ASR (GPU if available), and per-syllable tone analysis."""
from __future__ import annotations

import difflib
import io
import logging
import threading
from dataclasses import dataclass

import numpy as np

from . import config
from .text import (HAN_RE, ensure_traditional, fullwidth_punct, reading_tones, reading_tones_ex, sandhi,
                   sandhi_optional)

log = logging.getLogger("wenflow.speech")
SR = 16000

_model = None
_model_lock = threading.Lock()
_device_used = None


def decode_audio(data: bytes) -> np.ndarray:
    """Decode any browser audio (webm/opus, ogg, wav, mp4) to mono float32 at 16 kHz."""
    import av

    out = []
    with av.open(io.BytesIO(data), mode="r") as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SR)
        for frame in container.decode(stream):
            for rf in resampler.resample(frame):
                out.append(rf.to_ndarray().reshape(-1))
        for rf in resampler.resample(None):
            out.append(rf.to_ndarray().reshape(-1))
    if not out:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(out).astype(np.float32) / 32768.0


def to_wav_bytes(audio: np.ndarray) -> bytes:
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _preload_cuda_libs() -> None:
    """Load the pip-installed cuBLAS/cuDNN libraries globally so CTranslate2 can find them
    without LD_LIBRARY_PATH."""
    import ctypes
    import importlib.util
    from pathlib import Path

    spec = importlib.util.find_spec("nvidia")
    if not spec or not spec.submodule_search_locations:
        return
    base = Path(list(spec.submodule_search_locations)[0])
    for sub in ("cuda_nvrtc", "cublas", "cudnn"):
        libdir = base / sub / "lib"
        if not libdir.exists():
            continue
        # Load core libs first so dependants resolve.
        libs = sorted(libdir.glob("*.so*"), key=lambda p: (not p.name.startswith(("libcublasLt", "libcudnn.so", "libnvrtc.so")), p.name))
        for lib in libs:
            if lib.name.startswith("libnvblas"):
                continue  # NVBLAS hijacks every BLAS call in the process (NumPy, PyTorch) and aborts without a config
            try:
                ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def _get_model():
    global _model, _device_used
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        _preload_cuda_libs()
        from faster_whisper import WhisperModel

        devices = ["cuda", "cpu"] if config.WHISPER_DEVICE == "auto" else [config.WHISPER_DEVICE]
        last = None
        for dev in devices:
            try:
                ct = "float16" if dev == "cuda" else "int8"
                m = WhisperModel(config.WHISPER_MODEL, device=dev, compute_type=ct)
                # Force a tiny inference so CUDA/cuDNN problems surface here, not mid-request.
                list(m.transcribe(np.zeros(SR // 2, dtype=np.float32), language="zh")[0])
                _model, _device_used = m, dev
                log.info("whisper %s loaded on %s", config.WHISPER_MODEL, dev)
                return _model
            except Exception as e:  # noqa: BLE001
                log.warning("whisper on %s failed: %s", dev, e)
                last = e
        raise RuntimeError(f"Could not load Whisper: {last}")


def whisper_status() -> dict:
    return {"loaded": _model is not None, "device": _device_used, "model": config.WHISPER_MODEL}


TW_PROMPT = "以下是台灣國語的對話，請使用繁體中文。"


@dataclass
class CharTime:
    c: str
    start: float
    end: float


def transcribe(audio: np.ndarray, prompt: str | None = None, word_timestamps: bool = True) -> dict:
    """Returns {text, chars:[{c,start,end}], segments:[{start,end,text}]} in Traditional characters."""
    model = _get_model()
    segments, info = model.transcribe(
        audio, language="zh", initial_prompt=TW_PROMPT if prompt is None else prompt, word_timestamps=word_timestamps,
        vad_filter=len(audio) > SR * 30, beam_size=5,
    )
    out_segs, chars = [], []
    pending_break = False
    for seg in segments:
        text = fullwidth_punct(ensure_traditional(seg.text.strip()))
        out_segs.append({"start": seg.start, "end": seg.end, "text": text})
        if word_timestamps and seg.words:
            for w in seg.words:
                wt = ensure_traditional(w.word.strip())
                han = [c for c in wt if HAN_RE.match(c)]
                if not han:
                    if chars and wt:
                        pending_break = True
                    continue
                if chars and not HAN_RE.match(wt[0]):
                    pending_break = True
                step = (w.end - w.start) / len(han)
                for i, c in enumerate(han):
                    chars.append({"c": c, "start": w.start + i * step, "end": w.start + (i + 1) * step,
                                  "brk": bool(pending_break and i == 0)})
                pending_break = bool(wt and not HAN_RE.match(wt[-1]))
        if chars:
            pending_break = True
    return {"text": "".join(s["text"] for s in out_segs), "chars": chars, "segments": out_segs,
            "duration": float(len(audio) / SR)}


def transcribe_openai(audio: np.ndarray) -> dict:
    """Cloud fallback (no timestamps)."""
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    f = ("speech.wav", to_wav_bytes(audio), "audio/wav")
    r = client.audio.transcriptions.create(model=config.OPENAI_TRANSCRIBE_MODEL, file=f, language="zh", prompt=TW_PROMPT)
    text = fullwidth_punct(ensure_traditional(r.text))
    return {"text": text, "chars": [], "segments": [{"start": 0, "end": len(audio) / SR, "text": text}],
            "duration": float(len(audio) / SR)}


# ----------------------------------------------------------------------------------------------
# Tone analysis
# ----------------------------------------------------------------------------------------------

# Contour templates in semitones relative to the speaker's median pitch (5 points across the syllable).
TEMPLATES = {
    1: np.array([2.5, 2.6, 2.6, 2.6, 2.5]),
    2: np.array([-1.0, -0.8, 0.5, 2.0, 3.5]),
    3: np.array([-1.5, -3.0, -4.0, -4.0, -3.0]),  # connected-speech "half third" (low, may not rise)
    4: np.array([4.0, 3.0, 1.0, -1.0, -3.5]),
}


def pitch_track(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import parselmouth

    snd = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=SR)
    pitch = snd.to_pitch_ac(time_step=0.01, pitch_floor=70, pitch_ceiling=500)
    f0 = pitch.selected_array["frequency"]
    return pitch.xs(), f0


def intensity_db(audio: np.ndarray, times: np.ndarray) -> np.ndarray:
    win = int(0.025 * SR)
    out = np.empty(len(times))
    for k, t in enumerate(times):
        c = int(t * SR)
        seg = audio[max(0, c - win // 2): c + win // 2]
        out[k] = 10 * np.log10(np.mean(seg ** 2) + 1e-10) if len(seg) else -100
    return out


UNVOICED_INITIALS = ("b", "p", "d", "t", "g", "k", "j", "q", "x", "zh", "ch", "sh", "z", "c", "s", "f", "h")

# Weights for the boundary search (tuned on native Taiwanese TTS speech).
SEG_W = {"db": 0.08, "uv": 1.5, "prior": 2.0, "dur": 1.2, "win": 0.35}


def segment_syllables(chars: list[dict], pinyins: list[str], times: np.ndarray, f0: np.ndarray,
                      db: np.ndarray, span: tuple[float, float] | None = None) -> list[tuple[float, float]]:
    """Find syllable boundaries with dynamic programming over 10 ms frames.

    Combines: low intensity at boundaries, voicing breaks where the next syllable starts with a voiceless
    consonant, closeness to Whisper's rough timing, and a roughly even speaking rate.
    """
    n = len(chars)
    if n == 0:
        return []
    voiced = f0 > 0
    vt = times[voiced]
    start = chars[0]["start"]
    end = chars[-1]["end"]
    if span:
        start, end = span
    elif len(vt):
        cand = vt[(vt >= start - 0.25) & (vt <= start + 0.4)]
        start = float(cand[0]) if len(cand) else start
        cand = vt[(vt >= end - 0.4) & (vt <= end + 0.35)]
        end = float(cand[-1]) if len(cand) else end
    if n == 1:
        return [(start, end)]
    k = 5
    sdb = np.convolve(db, np.ones(k) / k, mode="same")
    ref = np.percentile(sdb[(times >= start) & (times <= end)], 90) if np.any((times >= start) & (times <= end)) else sdb.max()
    dbar = (end - start) / n
    priors = []
    for i in range(n - 1):
        whisper_b = (chars[i]["end"] + chars[i + 1]["start"]) / 2
        uniform_b = start + dbar * (i + 1)
        priors.append(0.5 * whisper_b + 0.5 * uniform_b)
    w = SEG_W
    # Candidate frames per boundary.
    cands, costs = [], []
    for i, p in enumerate(priors):
        idx = np.where((times > start + 0.05) & (times < end - 0.05) & (np.abs(times - p) <= w["win"]))[0]
        if len(idx) == 0:
            idx = np.array([int(np.argmin(np.abs(times - p)))])
        nxt = pinyins[i + 1] if i + 1 < len(pinyins) else ""
        uv_onset = nxt.startswith(UNVOICED_INITIALS)
        c = w["db"] * (sdb[idx] - ref)  # quieter is better (negative)
        if uv_onset:
            c = c - w["uv"] * (~voiced[idx]).astype(float)
        c = c + w["prior"] * ((times[idx] - p) / max(dbar, 0.08)) ** 2 * 0.25
        cands.append(idx)
        costs.append(c)
    # DP over boundaries.
    INF = 1e18
    best = [np.full(len(c), INF) for c in cands]
    back = [np.zeros(len(c), dtype=int) for c in cands]
    t0 = times[cands[0]]
    best[0] = costs[0] + w["dur"] * ((t0 - start - dbar) / dbar) ** 2
    best[0][t0 - start < 0.06] = INF
    for i in range(1, len(cands)):
        tp = times[cands[i - 1]][:, None]
        tc = times[cands[i]][None, :]
        d = tc - tp
        trans = best[i - 1][:, None] + w["dur"] * ((d - dbar) / dbar) ** 2
        trans[d < 0.06] = INF
        j = np.argmin(trans, axis=0)
        best[i] = trans[j, np.arange(len(cands[i]))] + costs[i]
        back[i] = j
    last_t = times[cands[-1]]
    final = best[-1] + w["dur"] * ((end - last_t - dbar) / dbar) ** 2
    final[end - last_t < 0.06] = INF
    sel = [int(np.argmin(final))]
    for i in range(len(cands) - 1, 0, -1):
        sel.append(int(back[i][sel[-1]]))
    sel.reverse()
    bounds = [float(times[cands[i][s]]) for i, s in enumerate(sel)]
    edges = [start] + bounds + [end]
    return [(edges[i], edges[i + 1]) for i in range(n)]


def find_pauses(times: np.ndarray, f0: np.ndarray, db: np.ndarray, lo: float, hi: float) -> list[tuple[float, float]]:
    """Silent or unvoiced stretches of >= 140 ms between lo and hi."""
    sdb = np.convolve(db, np.ones(5) / 5, mode="same")
    m = (times >= lo) & (times <= hi)
    if not m.any():
        return []
    ref = np.percentile(sdb[m], 90)
    quiet = m & ((sdb < ref - 25) | (f0 <= 0))
    out, run = [], None
    for t, q in zip(times, quiet):
        if q and run is None:
            run = t
        elif not q and run is not None:
            if t - run >= 0.14:
                out.append((run, t))
            run = None
    return out


def segment_by_phrase(chars: list[dict], pinyins: list[str], times: np.ndarray, f0: np.ndarray,
                      db: np.ndarray) -> list[tuple[float, float]]:
    """Split at punctuation-marked phrase breaks (matched to real pauses), then segment each phrase."""
    if not chars:
        return []
    groups, cur = [], []
    for i, c in enumerate(chars):
        if c.get("brk") and cur:
            groups.append(cur)
            cur = []
        cur.append(i)
    groups.append(cur)
    whole = segment_syllables(chars, pinyins, times, f0, db)
    if len(groups) == 1:
        return whole
    lo, hi = whole[0][0], whole[-1][1]
    pauses = find_pauses(times, f0, db, lo, hi)
    spans = []
    s = lo
    for gi in range(len(groups) - 1):
        guess = (chars[groups[gi][-1]]["end"] + chars[groups[gi + 1][0]]["start"]) / 2
        near = [p for p in pauses if p[0] > s + 0.1 and abs((p[0] + p[1]) / 2 - guess) < 0.6]
        if near:
            p = min(near, key=lambda p: abs((p[0] + p[1]) / 2 - guess) - 0.3 * (p[1] - p[0]))
            spans.append((s, p[0]))
            s = p[1]
        else:
            spans.append((s, guess))
            s = guess
    spans.append((s, hi))
    out = []
    for g, sp in zip(groups, spans):
        sub = [chars[i] for i in g]
        out.extend(segment_syllables(sub, [pinyins[i] for i in g], times, f0, db, span=sp))
    return out


def refine_boundaries(chars: list[dict], times: np.ndarray, f0: np.ndarray, db: np.ndarray) -> list[tuple[float, float]]:
    """Snap Whisper's approximate character boundaries to nearby intensity valleys / voicing breaks."""
    n = len(chars)
    if n == 0:
        return []
    cost = db.copy()
    cost[f0 <= 0] -= 12  # unvoiced frames (consonant onsets, pauses) are good boundaries
    bounds = []
    for i in range(n - 1):
        guess = (chars[i]["end"] + chars[i + 1]["start"]) / 2
        lo = max(chars[i]["start"] + 0.04, guess - 0.12)
        hi = min(chars[i + 1]["end"] - 0.04, guess + 0.12)
        if bounds:
            lo = max(lo, bounds[-1] + 0.05)
        m = (times >= lo) & (times <= hi)
        if m.sum() == 0:
            bounds.append(max(guess, bounds[-1] + 0.05) if bounds else guess)
            continue
        idx = np.where(m)[0]
        # Prefer a valley close to the guess: small distance penalty.
        score = cost[idx] + 15 * np.abs(times[idx] - guess)
        bounds.append(float(times[idx[np.argmin(score)]]))
    voiced_t = times[f0 > 0]
    start = chars[0]["start"]
    end = chars[-1]["end"]
    if len(voiced_t):
        near = voiced_t[(voiced_t >= start - 0.2) & (voiced_t <= (bounds[0] if bounds else end))]
        if len(near):
            start = float(near[0])
        near = voiced_t[(voiced_t >= (bounds[-1] if bounds else start)) & (voiced_t <= end + 0.25)]
        if len(near):
            end = float(near[-1])
    edges = [start] + bounds + [end]
    return [(edges[i], edges[i + 1]) for i in range(n)]


def _detrend(times: np.ndarray, st: np.ndarray) -> np.ndarray:
    """Remove sentence-level declination with a robust linear fit over voiced frames."""
    ok = ~np.isnan(st)
    if ok.sum() < 10:
        return st
    t, v = times[ok], st[ok]
    a, b = np.polyfit(t, v, 1)
    resid = v - (a * t + b)
    keep = np.abs(resid) < 2.5 * np.std(resid) + 1e-6
    a, b = np.polyfit(t[keep], v[keep], 1)
    a = min(a, 0.0)  # only remove downward drift
    out = st - (a * (times - t.mean()))
    return out - np.nanmedian(out)


def syllable_contour(times: np.ndarray, st: np.ndarray, start: float, end: float) -> np.ndarray | None:
    """5-point contour over the tone-bearing part of a syllable (skip onset transition)."""
    dur = end - start
    m = (times >= start + 0.2 * dur) & (times <= end - 0.08 * dur)
    seg = st[m]
    seg = seg[~np.isnan(seg)]
    if len(seg) < 4:
        m = (times >= start) & (times <= end)
        seg = st[m]
        seg = seg[~np.isnan(seg)]
        if len(seg) < 3:
            return None
    # Light median smoothing to remove octave jumps.
    if len(seg) >= 5:
        seg = np.array([np.median(seg[max(0, k - 2): k + 3]) for k in range(len(seg))])
    return np.interp(np.linspace(0, len(seg) - 1, 5), np.arange(len(seg)), seg)


def _classify_template(contour: np.ndarray) -> tuple[int, dict[int, float]]:
    """Fallback: distance to each template, combining shape (mean-removed) and register."""
    scores = {}
    for t, tpl in TEMPLATES.items():
        shape = np.mean((contour - contour.mean() - (tpl - tpl.mean())) ** 2)
        register = (contour.mean() - tpl.mean()) ** 2
        scores[t] = float(shape + 0.5 * register)
    best = min(scores, key=scores.get)
    return best, scores


def syllable_features(contours: list[np.ndarray | None], durs: list[float]) -> list[np.ndarray | None]:
    """Feature vector per syllable using its neighbours for local register normalisation."""
    means = [None if c is None else float(c.mean()) for c in contours]
    voiced_durs = [d for d, c in zip(durs, contours) if c is not None] or [0.2]
    dbar = float(np.mean(voiced_durs))
    feats = []
    for i, c in enumerate(contours):
        if c is None:
            feats.append(None)
            continue
        nb = [m for m in (means[i - 1] if i > 0 else None, means[i + 1] if i + 1 < len(means) else None) if m is not None]
        local = means[i] - (np.mean(nb) if nb else means[i])
        prev = contours[i - 1] if i > 0 and contours[i - 1] is not None else None
        nxt = contours[i + 1] if i + 1 < len(contours) and contours[i + 1] is not None else None
        shape = c - c.mean()
        f = np.concatenate([
            shape,
            [c[4] - c[0], c[2] - c[0], c[4] - c[2], c.max() - c.min(),
             means[i], local,
             (c[0] - prev[4]) if prev is not None else 0.0,
             (nxt[0] - c[4]) if nxt is not None else 0.0,
             durs[i] / dbar, float(np.argmin(c)) / 4, float(np.argmax(c)) / 4],
        ])
        feats.append(f)
    return feats


_tone_model = None

# A flag is only shown as an error when the classifier is this sure (see scripts/train_tone_model.py
# for the false-alarm / detection trade-off these thresholds were chosen on).
SURE_DETECTED = 0.85
SURE_EXPECTED = 0.05
LENIENT_EXPECTED = 0.25


def normalize_utterance(feats: list[np.ndarray | None]) -> list[np.ndarray | None]:
    """Scale pitch features by the speaker's range in this utterance, so a narrow or wide voice
    is judged on the shape of its tones rather than on how far its pitch travels."""
    have = [f for f in feats if f is not None]
    if not have:
        return feats
    F = np.array(have, dtype=np.float64)
    contours = F[:, :5] + F[:, 9:10]
    spread = max(float(contours.std()), 0.8)
    centre = float(contours.mean())
    out: list[np.ndarray | None] = []
    for f in feats:
        if f is None:
            out.append(None)
            continue
        g = np.array(f, dtype=np.float64)
        g[:9] /= spread
        g[9] = (g[9] - centre) / spread
        g[10:13] /= spread
        out.append(g)
    return out


def _load_tone_model():
    global _tone_model
    if _tone_model is None:
        import json

        p = config.CONTENT_DIR / "tone_model.json"
        if not p.exists():
            return {}  # not trained yet: look again next time instead of caching the absence
        m = json.loads(p.read_text())
        if m.get("type") != "mlp":
            return {}
        _tone_model = {
            "mu": np.array(m["mu"]), "sd": np.array(m["sd"]), "classes": m["classes"],
            "nets": [[(np.array(layer["W"]), np.array(layer["b"])) for layer in net] for net in m["nets"]],
        }
    return _tone_model


def classify_features(f: np.ndarray) -> tuple[int, dict[int, float]] | None:
    """Tone probabilities from a small ensemble of MLPs over normalised syllable features."""
    m = _load_tone_model()
    if not m:
        return None
    x = (np.asarray(f, dtype=np.float64) - m["mu"]) / m["sd"]
    total = np.zeros(len(m["classes"]))
    for net in m["nets"]:
        h = x
        for k, (W, b) in enumerate(net):
            h = W @ h + b
            if k < len(net) - 1:
                h = np.maximum(h, 0.0)
        e = np.exp(h - h.max())
        total += e / e.sum()
    p = total / len(m["nets"])
    best = m["classes"][int(np.argmax(p))]
    return best, {c: round(float(pp), 3) for c, pp in zip(m["classes"], p)}


def syllable_table(audio: np.ndarray, asr: dict) -> tuple[list[dict], dict]:
    """Segment the recognised characters and extract contours + features."""
    times, f0 = pitch_track(audio)
    voiced = f0[f0 > 0]
    if len(voiced) < 5:
        return [], {}
    median = float(np.median(voiced))
    st = np.where(f0 > 0, 12 * np.log2(np.maximum(f0, 1) / median), np.nan)
    st = _detrend(times, st)
    db = intensity_db(audio, times)
    heard = [dict(h) for h in asr["chars"]]
    heard_py = [p for _, _, p in reading_tones("".join(h["c"] for h in heard))]
    if len(heard_py) != len(heard):
        heard_py = [""] * len(heard)
    for h, (s, e) in zip(heard, segment_by_phrase(heard, heard_py, times, f0, db)):
        h["start"], h["end"] = s, e
    contours = [syllable_contour(times, st, h["start"], h["end"]) for h in heard]
    feats = syllable_features(contours, [h["end"] - h["start"] for h in heard])
    for h, c, f in zip(heard, contours, feats):
        h["contour"], h["feat"] = c, f
    return heard, {"times": times, "st": st, "median": median}


def analyze_tones(audio: np.ndarray, target_text: str | None, asr: dict | None = None) -> dict:
    """Align recognised characters to the target text and grade each syllable's tone."""
    if asr is None:
        asr = transcribe(audio)
    heard, pitch = syllable_table(audio, asr)
    if not pitch:
        return {"asr": asr, "syllables": [], "score": None, "error": "No voiced speech detected."}
    target = target_text or asr["text"]
    exp, breaks, spans = reading_tones_ex(target)  # (char, tone, pinyin), phrase starts, word spans
    exp_chars = [e[0] for e in exp]
    surface = sandhi([e[1] for e in exp], exp_chars, breaks, spans)
    either = sandhi_optional([e[1] for e in exp], breaks)  # 2nd or 3rd tone both fine here
    heard_chars = [h["c"] for h in heard]

    sm = difflib.SequenceMatcher(a=exp_chars, b=heard_chars, autojunk=False)
    mapping: dict[int, int] = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            mapping[blk.a + k] = blk.b + k
    # Also map replaced runs of equal length (mispronounced chars still carry a tone).
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        if tag == "replace" and a1 - a0 == b1 - b0:
            for k in range(a1 - a0):
                mapping[a0 + k] = b0 + k

    norm = normalize_utterance([h["feat"] for h in heard])
    syllables = []
    graded = correct = 0
    for i, (ch, tone, py) in enumerate(exp):
        item = {"c": ch, "py": py, "expected": surface[i], "citation": tone, "heard": None,
                "detected": None, "probs": None, "ok": None, "contour": None, "start": None, "end": None}
        j = mapping.get(i)
        if j is not None:
            h = heard[j]
            item.update({"heard": h["c"], "start": round(h["start"], 3), "end": round(h["end"], 3)})
            if h["contour"] is not None:
                model = classify_features(norm[j]) if norm[j] is not None else None
                det, probs = model or _classify_template(h["contour"])
                item["detected"] = det
                item["probs"] = probs if model else None
                item["contour"] = [round(float(x), 2) for x in h["contour"]]
                if surface[i] in (1, 2, 3, 4):
                    graded += 1
                    p_exp = probs.get(surface[i], 0.0) if model else 0.0
                    # Give the benefit of the doubt when the target tone is a close second.
                    ok = det == surface[i] or p_exp >= LENIENT_EXPECTED or (i in either and det in (2, 3))
                    item["ok"] = bool(ok)
                    # "sure": a confident mismatch worth showing as an error.
                    item["sure"] = bool(model and not ok and probs.get(det, 0.0) >= SURE_DETECTED and p_exp <= SURE_EXPECTED)
                    correct += ok
        syllables.append(item)

    times, st = pitch["times"], pitch["st"]
    track = [[round(float(t), 3), None if np.isnan(v) else round(float(v), 2)] for t, v in zip(times, st)]
    return {
        "asr": {"text": asr["text"], "duration": asr["duration"]},
        "target": target,
        "char_match": round(sm.ratio(), 3),
        "syllables": syllables,
        "score": round(correct / graded, 3) if graded else None,
        "graded": graded,
        "median_hz": round(pitch["median"], 1),
        "track": track[::2],
        "templates": {k: v.tolist() for k, v in TEMPLATES.items()},
    }
