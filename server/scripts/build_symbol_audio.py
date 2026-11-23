"""Record the names of the 37 zhuyin symbols (bo po mo fo, de te ne le ...) as fixed audio clips.

The zh-TW voice 曉臻 reads a bare symbol by its name, in the level tone used when reciting the chart,
so most clips are simply the symbol itself. Two adjustments:

* ㄅ ㄆ ㄇ ㄈ — the voice says a neutral "bə pə mə fə" (how many Taiwanese teachers blend them).
  The standard names are bo po mo fo, so these are recorded from 玻 坡 摸 佛 instead.
* 佛 is fó, a rising tone; its pitch is flattened so all four share the level tone of the chant.

The other voices are less consistent, so the clips are made once (the server runs this script
by itself on first start) and kept in data/symbols/<codepoint>.(mp3|wav).

    uv run python scripts/build_symbol_audio.py
"""
from __future__ import annotations

import asyncio
import io
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import edge_tts  # noqa: E402

from wenflow import config  # noqa: E402

VOICE = "zh-TW-HsiaoChenNeural"
SYMBOLS = "ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙㄧㄨㄩㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦ"
FROM_CHAR = {"ㄅ": "玻", "ㄆ": "坡", "ㄇ": "摸", "ㄈ": "佛"}
FLATTEN = {"ㄈ"}
OUT = config.DATA_DIR / "symbols"
SR = 24000


async def record(text: str) -> bytes:
    for attempt in range(5):
        try:
            chunks = []
            async for chunk in edge_tts.Communicate(text, VOICE, rate="-8%").stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            if chunks:
                return b"".join(chunks)
        except Exception as e:  # noqa: BLE001
            print("retry", text, e)
        await asyncio.sleep(1 + attempt)
    raise RuntimeError(f"no audio for {text}")


def decode(mp3: bytes) -> np.ndarray:
    import av

    out = []
    with av.open(io.BytesIO(mp3)) as c:
        rs = av.AudioResampler(format="s16", layout="mono", rate=SR)
        for frame in c.decode(c.streams.audio[0]):
            out += [f.to_ndarray().reshape(-1) for f in rs.resample(frame)]
        out += [f.to_ndarray().reshape(-1) for f in rs.resample(None)]
    return np.concatenate(out).astype(np.float64) / 32768.0


def level_pitch(samples: np.ndarray, hz: float) -> np.ndarray:
    """Resynthesise with a flat pitch contour (Praat overlap-add)."""
    import parselmouth
    from parselmouth.praat import call

    snd = parselmouth.Sound(samples, sampling_frequency=SR)
    manip = call(snd, "To Manipulation", 0.01, 100, 500)
    tier = call(manip, "Extract pitch tier")
    call(tier, "Remove points between", 0, snd.duration)
    call(tier, "Add point", 0.0, hz)
    call(tier, "Add point", snd.duration, hz)
    call([tier, manip], "Replace pitch tier")
    return call(manip, "Get resynthesis (overlap-add)").values[0]


def median_pitch(samples: np.ndarray) -> float:
    import parselmouth

    f0 = parselmouth.Sound(samples, sampling_frequency=SR).to_pitch_ac(pitch_floor=100, pitch_ceiling=500).selected_array["frequency"]
    return float(np.median(f0[f0 > 0]))


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


async def main() -> None:
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*"):
        old.unlink()
    levels: list[float] = []
    for sym in SYMBOLS:
        data = await record(FROM_CHAR.get(sym, sym))
        stem = OUT / f"{ord(sym):04x}"
        if sym in FLATTEN:
            samples = decode(data)
            write_wav(stem.with_suffix(".wav"), level_pitch(samples, float(np.mean(levels)) if levels else median_pitch(samples)))
        else:
            stem.with_suffix(".mp3").write_bytes(data)
            if sym in FROM_CHAR:  # the level tone of 玻 / 坡 / 摸 sets the target for 佛
                levels.append(median_pitch(decode(data)))
        print(sym, FROM_CHAR.get(sym, "symbol"), "flattened" if sym in FLATTEN else "")


if __name__ == "__main__":
    asyncio.run(main())
