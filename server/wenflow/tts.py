"""Text-to-speech with Taiwanese voices. Cached on disk by (engine, voice, rate, text).

Two corrections are applied before the Microsoft zh-TW voices are asked to speak:

* A few words the voices read the mainland way (椰子 yē, 悄悄 qiāo, 擁抱 yōng ...) are respelled
  with characters that have the Taiwan reading (content/tts_respell.json).
* A single character on its own is where the voice's intonation most often bends the tone
  (a lone 媽 comes out rising, like the particle 嗎). The clip's pitch is checked against the
  tone it should carry, and if it fails the character is re-synthesised in a different frame.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re

from . import config

log = logging.getLogger("wenflow.tts")
CACHE = config.DATA_DIR / "tts_cache"
CACHE.mkdir(exist_ok=True)

EDGE_VOICES = {
    "zh-TW-HsiaoChenNeural": "曉臻 (Microsoft, female)",
    "zh-TW-HsiaoYuNeural": "曉雨 (Microsoft, female)",
    "zh-TW-YunJheNeural": "雲哲 (Microsoft, male)",
}
OPENAI_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse")

_HAN1 = re.compile(r"^[㐀-鿿]$")
_FRAMES = ("{c}", "「{c}」", "{c}，", "{c}！", "{c}。")
_CALIBRATION = "今天天氣很好，我們一起去夜市吃東西。"
_median: dict[str, float] = {}


def _respell(text: str) -> tuple[str, bool]:
    from .content_store import load_json

    table = load_json("tts_respell.json", {}) or {}
    out = text
    for word, spoken in table.items():
        if word in out:
            out = out.replace(word, spoken)
    return out, out != text


async def synthesize(text: str, voice: str | None = None, rate: int = 0, engine: str | None = None) -> bytes:
    from . import voice_local

    if voice == voice_local.VOICE_ID and engine in (None, "local"):
        data = await _local(text, rate)
        if data:
            return data
        voice = None  # the local voice is loading or could not say this cleanly: use the cloud voice
    engine = engine or config.TTS_ENGINE
    if engine == "local":
        engine = "edge"
    voice = voice or config.TTS_VOICE
    if voice == voice_local.VOICE_ID:
        voice = config.TTS_VOICE
    spoken, changed = (text, False) if engine == "openai" else _respell(text)
    single = engine != "openai" and bool(_HAN1.match(text))
    tag = "|tone2" if single else "|r1" if changed else ""
    key = hashlib.sha1(f"{engine}|{voice}|{rate}|{text}{tag}".encode()).hexdigest()
    path = CACHE / f"{key}.mp3"
    if path.exists():
        return path.read_bytes()
    if engine == "openai":
        data = _openai_tts(text, rate, voice if voice in OPENAI_VOICES else "coral")
    elif single:
        data = await _single_character(text, voice, rate)
    else:
        data = await _edge(spoken, voice, rate)
    if data:
        path.write_bytes(data)
    return data


async def _edge(text: str, voice: str, rate: int) -> bytes:
    import edge_tts

    data = b""
    for attempt in range(4):
        try:
            comm = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%")
            chunks = []
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            data = b"".join(chunks)
            if data:
                break
        except Exception:  # noqa: BLE001 - transient service errors
            if attempt == 3:
                raise
        await asyncio.sleep(0.6 * (attempt + 1))
    return data


# ----------------------------------------------------------------------------------------------
# Single characters: make sure the tone you hear is the tone on the page
# ----------------------------------------------------------------------------------------------

def _voiced_f0(mp3: bytes):
    """F0 (Hz) of the longest voiced stretch in a clip, and of all voiced frames."""
    import numpy as np
    import parselmouth

    from . import speech

    audio = speech.decode_audio(mp3)
    f0 = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=speech.SR).to_pitch_ac(
        time_step=0.01, pitch_floor=70, pitch_ceiling=500).selected_array["frequency"]
    runs, cur = [], []
    for x in f0:
        if x > 0:
            cur.append(x)
        else:
            if len(cur) >= 6:
                runs.append(np.array(cur))
            cur = []
    if len(cur) >= 6:
        runs.append(np.array(cur))
    return (max(runs, key=len) if runs else None), f0[f0 > 0]


def tone_ok(tone: int, f0, median: float) -> bool:
    """Does a syllable's pitch contour look like the citation form of this tone?
    1 high and level · 2 rising · 3 low (a final rise is optional in Taiwan) · 4 falling."""
    import numpy as np

    st = 12 * np.log2(f0 / median)
    k = max(2, len(st) // 5)
    start, end, low, mean = st[:k].mean(), st[-k:].mean(), st.min(), st.mean()
    if tone == 1:
        return abs(end - start) < 2.2 and mean > 0.5
    if tone == 2:
        return end - low > 1.6 and end > start - 0.8
    if tone == 3:
        return mean < -1.0 and end - low < 4.5
    if tone == 4:
        return start - end > 3.0
    return True


async def _voice_median(voice: str) -> float:
    if voice not in _median:
        import numpy as np

        data = await synthesize(_CALIBRATION, voice=voice)
        _, voiced = await asyncio.to_thread(_voiced_f0, data)
        _median[voice] = float(np.median(voiced)) if len(voiced) else 200.0
    return _median[voice]


async def _single_character(char: str, voice: str, rate: int) -> bytes:
    from . import text as textmod

    toks = await asyncio.to_thread(textmod.annotate, char, False)
    tone = toks[0]["chars"][0]["t"] if toks and toks[0].get("han") else 0
    bare = await _edge(char, voice, rate)
    if tone not in (1, 2, 3, 4) or not bare:
        return bare
    try:
        median = await _voice_median(voice)
        for frame in _FRAMES:
            data = bare if frame == "{c}" else await _edge(frame.format(c=char), voice, rate)
            if not data:
                continue
            f0, _ = await asyncio.to_thread(_voiced_f0, data)
            if f0 is not None and tone_ok(tone, f0, median):
                if frame != "{c}":
                    log.info("tts: %s spoken as %s to keep tone %d", char, frame.format(c=char), tone)
                return data
    except Exception as e:  # noqa: BLE001 - never let the check break playback
        log.warning("tone check failed for %s: %s", char, e)
    return bare


# ----------------------------------------------------------------------------------------------
# The local Taiwanese voice (BreezyVoice): every clip is checked before it is kept
# ----------------------------------------------------------------------------------------------

_local_locks: dict[str, asyncio.Lock] = {}
_ACCENT = (("zh", "z"), ("ch", "c"), ("sh", "s"), ("ng", "n"))  # distinctions a Taiwanese accent (and the recogniser) blur


def _syllables(s: str) -> list[str]:
    """Toneless syllables of the Han characters in s, with accent-neutral spelling."""
    from . import text as textmod
    from .zhuyin import split_tone

    out = []
    for tok in textmod.annotate(s, with_gloss=False):
        if tok["han"]:
            for ch in tok["chars"]:
                base = split_tone(ch["py"])[0] if ch["py"] else ch["c"]
                for a, b in _ACCENT:
                    base = base.replace(a, b)
                out.append(base)
    return out


def _wav_seconds(wav: bytes) -> float:
    import io
    import wave

    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def verify_clip(wav: bytes, text: str, median: float | None = None) -> bool:
    """Is this clip really `text`? Length must be plausible, a speech recogniser must hear the same
    syllables, and a single character must carry its tone."""
    import difflib

    from . import speech
    from . import text as textmod

    want = _syllables(text)
    n = len(want)
    dur = _wav_seconds(wav)
    if n == 0:
        return dur > 0.15
    if not (0.16 * n + 0.12 < dur < 0.8 * n + 2.2):
        return False
    heard = speech.transcribe(speech.decode_audio(wav), prompt="，。", word_timestamps=False)["text"]
    got = _syllables(heard)
    if n == 1:
        if want[0] not in got[:2]:
            return False
        toks = textmod.annotate(text, with_gloss=False)
        tone = next((c["t"] for t in toks if t["han"] for c in t["chars"]), 0)
        if tone in (1, 2, 3, 4) and median:
            f0, _ = _voiced_f0(wav)
            return f0 is not None and tone_ok(tone, f0, median)
        return True
    ratio = difflib.SequenceMatcher(a=want, b=got, autojunk=False).ratio()
    if ratio < (0.99 if n <= 3 else 0.86):
        return False
    if n <= 6:
        # Short items are where a wrong tone matters most (a word card, a pronunciation example):
        # reject the clip if any syllable is confidently in a different tone from the one shown.
        try:
            report = speech.analyze_tones(speech.decode_audio(wav), text)
            if any(sy.get("sure") for sy in report.get("syllables") or []):
                return False
        except Exception:  # noqa: BLE001 - the tone check is a bonus, not a gate
            pass
    return True


def _stretch(wav: bytes, factor: float) -> bytes:
    """Slow a clip down without changing its pitch."""
    import io
    import wave

    import numpy as np
    import parselmouth
    from parselmouth.praat import call

    with wave.open(io.BytesIO(wav)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
    y = call(parselmouth.Sound(x, sampling_frequency=sr), "Lengthen (overlap-add)", 75, 600, factor).values[0]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


async def _local(text: str, rate: int) -> bytes | None:
    from . import voice_local

    key = hashlib.sha1(f"local|breezy|{text}|v3".encode()).hexdigest()
    path = CACHE / f"{key}.wav"
    slow = CACHE / f"{key}.r{rate}.wav"
    if rate and slow.exists():
        return slow.read_bytes()
    failed = CACHE / f"{key}.fail"  # the local voice could not say this correctly: don't try again each time
    if failed.exists():
        return None
    if not path.exists():
        st = voice_local.status()
        if not st["ready"]:
            voice_local.start()
            return None
        lock = _local_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if not path.exists() and not failed.exists():
                wav, gave_up = await asyncio.to_thread(_local_make, text)
                if not wav:
                    if gave_up:
                        failed.touch()
                    return None
                path.write_bytes(wav)
        _local_locks.pop(key, None)
        if not path.exists():
            return None
    data = path.read_bytes()
    if rate:
        try:
            data = await asyncio.to_thread(_stretch, data, max(0.6, min(1.8, 1 / (1 + rate / 100))))
            slow.write_bytes(data)
        except Exception as e:  # noqa: BLE001
            log.warning("could not change speed: %s", e)
    return data


def _local_median() -> float | None:
    """Median pitch of the local voice, measured once on a full sentence."""
    import numpy as np

    from . import voice_local

    if "local" not in _median:
        try:
            _, voiced = _voiced_f0(voice_local.synth(_CALIBRATION, seed=0))
            _median["local"] = float(np.median(voiced)) if len(voiced) else 0.0
        except Exception:  # noqa: BLE001
            return None
    return _median["local"] or None


def citation(char: str) -> str | None:
    """How a character is named aloud in Taiwan: 馬 -> 「馬，馬路的馬」.

    A generative voice is unreliable on a one-syllable request, and this is also simply how people
    say which character they mean. The word is a common one in which the character keeps the reading
    it has on its own."""
    from . import dictionary
    from . import text as textmod

    import math

    def reading(s: str, i: int) -> str:
        chars = [c for t in textmod.annotate(s, with_gloss=False) if t["han"] for c in t["chars"]]
        return chars[i]["zy"] if i < len(chars) else ""

    own = reading(char, 0)
    rows = dictionary._conn().execute(
        "SELECT trad, max(freq) f, min(hsk) h FROM entries WHERE trad LIKE ? AND length(trad)=2 AND proper=0 "
        "GROUP BY trad ORDER BY f DESC LIMIT 80", (f"%{char}%",)).fetchall()
    best, best_score = None, -1.0
    for r in rows:
        w, f = r["trad"], r["f"] or 0
        if "的" in w or textmod.to_traditional(w) != w or (f < 150 and r["h"] is None):
            continue
        i = w.index(char)
        if reading(w, i) != own:
            continue
        other = w[1 - i]
        # Everyday words: on the HSK lists, frequent, built with a common second character.
        score = (0.5 * (7 - r["h"]) if r["h"] else 0.0) + math.log10(f + 1) \
            + 0.6 * math.log10(dictionary.word_info(other)[0] + 1) + (0.4 if i == 0 else 0.0)
        if score > best_score:
            best, best_score = w, score
    return f"{char}，{best}的{char}。" if best else None


def _first_syllable_f0(wav: bytes):
    """Pitch of the first syllable of a clip (the stretch of voicing before the first pause)."""
    import numpy as np
    import parselmouth

    from . import speech

    audio = speech.decode_audio(wav)
    f0 = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=speech.SR).to_pitch_ac(
        time_step=0.01, pitch_floor=70, pitch_ceiling=500).selected_array["frequency"]
    cur = []
    for x in f0:
        if x > 0:
            cur.append(x)
        elif len(cur) >= 6:
            break
        else:
            cur = []
    return np.array(cur) if len(cur) >= 6 else None


def _local_make(text: str) -> tuple[bytes | None, bool]:
    """Up to four attempts (different sampling seeds, with and without reading marks); keep the first that
    verifies. Returns (clip, gave_up): gave_up is True when every attempt was made and none passed."""
    from . import text as textmod
    from . import voice_local

    seed = int(hashlib.sha1(text.encode()).hexdigest()[:6], 16)
    single = bool(_HAN1.match(text))
    spoken = (citation(text) if single else None) or text
    tone = 0
    if single:
        toks = textmod.annotate(text, with_gloss=False)
        tone = next((c["t"] for t in toks if t["han"] for c in t["chars"]), 0)
    cited = single and spoken != text
    marked = voice_local.annotate(spoken)
    median = _local_median() if single else None
    for attempt, send in enumerate((marked, spoken, marked, spoken)):
        try:
            wav = voice_local.synth(send, seed=seed + attempt)
            ok = verify_clip(wav, spoken, None if cited else median)
            if ok and cited and tone in (1, 2, 3, 4) and median:
                f0 = _first_syllable_f0(wav)
                ok = f0 is not None and tone_ok(tone, f0, median)
            if ok:
                if attempt:
                    log.info("local voice: %r accepted on attempt %d", text[:20], attempt + 1)
                return wav, False
        except Exception as e:  # noqa: BLE001
            log.warning("local voice failed for %r: %s", text[:20], e)
            return None, False
    log.info("local voice: %r did not verify, using the cloud voice", text[:20])
    return None, True


def _openai_tts(text: str, rate: int, voice: str = "coral") -> bytes:
    from openai import OpenAI

    client = OpenAI(api_key=config.OPENAI_API_KEY)
    r = client.audio.speech.create(
        model="gpt-4o-mini-tts", voice=voice, input=text, response_format="mp3",
        instructions="Speak natural Taiwanese Mandarin (台灣國語) with a Taipei accent, friendly and clear."
        + (" Speak slowly for a learner." if rate < 0 else ""),
    )
    return r.read()
