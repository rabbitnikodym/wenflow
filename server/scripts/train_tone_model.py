"""Train the tone classifier on native Taiwanese neural-TTS speech.

Synthesises sentences with the zh-TW voices at normal and slow speed, runs Whisper + syllable
segmentation, and fits a small ensemble of MLPs over per-syllable pitch features.
Writes wenflow/content/tone_model.json and prints leave-one-voice-out accuracy, the false-alarm
rate of confident flags, and the share of (simulated) wrong tones those flags catch.

    uv run python scripts/train_tone_model.py [--max 200]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wenflow import config, speech, tts  # noqa: E402
from wenflow import g2p  # noqa: E402
from wenflow.content_store import grammar_points, scenarios, taiwan_vocab  # noqa: E402
from wenflow.text import HAN_RE, reading_tones_ex, sandhi, sandhi_optional  # noqa: E402

BASE = [
    "我昨天跟朋友去夜市吃東西，真的很好吃。", "你今天下班以後要不要一起去喝珍珠奶茶？",
    "這個週末颱風要來，記得多買一點泡麵。", "老闆，我要一杯半糖少冰的綠茶，謝謝。",
    "他每天騎機車上班，大概要二十分鐘。", "那些年我們一起追的女孩，是一部很感人的電影。",
    "請問捷運站怎麼走？我第一次來台北。", "我覺得這家早餐店的蛋餅比較好吃。",
    "學測快到了，大家都在補習班念書。", "天氣這麼熱，我們去便利商店買飲料吧。",
    "媽媽說今天晚上要煮牛肉麵。", "高鐵票我已經在網路上訂好了。", "你有沒有看過那部新的電視劇？",
    "我們班上的同學都很喜歡打籃球。", "這件衣服太貴了，可以算便宜一點嗎？", "週末我想去陽明山爬山。",
    "沈佳宜是班上成績最好的女生。", "柯景騰上課常常不專心，老師很頭痛。", "外面下大雨，記得帶雨傘。",
    "他的中文說得比我還流利。", "我等一下要去郵局寄包裹。", "醫生說我要多休息，多喝水。",
    "這次考試我考得不太好，有點難過。", "你可以幫我拍一張照片嗎？", "颱風天公司放假，大家都很開心。",
    "我住在台中，離火車站不遠。", "阿嬤做的菜真的是全世界最好吃的。", "我們約七點在捷運站門口見面。",
    "最近工作很忙，常常加班到很晚。", "台灣的便利商店幾乎什麼都買得到。", "他們兩個從國中就認識了。",
    "如果明天不下雨，我們就去海邊。", "請你把冷氣關小一點，好冷喔。", "這家咖啡廳的氣氛很好。",
    "她每天早上都會去公園跑步。", "我想學怎麼用注音打字。", "這本小說我已經看了三遍了。",
    "你週末有空嗎？要不要一起去看電影？", "這裡的牛肉麵又便宜又好吃。", "我們下次再一起出來玩吧。",
]


def corpus(max_n: int) -> list[str]:
    sents = list(BASE)
    for v in taiwan_vocab():
        if v.get("register") != "vulgar" and v.get("example", {}).get("zh"):
            sents.append(v["example"]["zh"])
    for g in grammar_points():
        sents += [e["zh"] for e in g.get("examples", [])]
    for s in scenarios():
        sents += [p["zh"] for p in s.get("key_phrases", [])]
    sents = [s for s in dict.fromkeys(sents) if 6 <= len(HAN_RE.findall(s)) <= 30]
    random.Random(0).shuffle(sents[len(BASE):])
    return sents[:max_n]


async def synth_all(items):
    """Synthesise with a few requests in flight at once (results are cached on disk)."""
    sem = asyncio.Semaphore(6)
    done = 0

    async def one(text, voice, rate):
        nonlocal done
        async with sem:
            try:
                if voice.startswith("openai:"):
                    data = await asyncio.to_thread(asyncio.run, tts.synthesize(text, voice=voice[7:], rate=rate, engine="openai"))
                else:
                    data = await tts.synthesize(text, voice=voice, rate=rate)
            except Exception as e:  # noqa: BLE001
                print("tts failed", text, voice, e)
                data = b""
        done += 1
        if done % 100 == 0:
            print(f"  synthesised {done}/{len(items)}", flush=True)
        return data

    return await asyncio.gather(*(one(*it) for it in items))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=160)
    ap.add_argument("--extra-voices", default="onyx,ash,echo,sage,nova", help="OpenAI TTS voices to add as extra speakers")
    ap.add_argument("--extra-sentences", type=int, default=110)
    args = ap.parse_args()
    sents = corpus(args.max)
    voices = list(tts.EDGE_VOICES)
    items = [(s, v, r) for s in sents for v in voices for r in (0, -30)]
    # More speakers, especially male ones, so the model is not tuned to three voices.
    extra = [f"openai:{v}" for v in args.extra_voices.split(",") if v] if config.OPENAI_API_KEY else []
    items += [(s, v, 0) for s in sents[: args.extra_sentences] for v in extra]
    voices += extra
    print(f"{len(sents)} sentences, {len(items)} utterances", flush=True)
    cache_p = config.DATA_DIR / "tone_train_cache_v2.pkl"
    cache = pickle.load(open(cache_p, "rb")) if cache_p.exists() else {}
    todo = [it for it in items if it not in cache]
    audios = asyncio.run(synth_all(todo))
    for n, (it, mp3) in enumerate(zip(todo, audios)):
        if n % 100 == 0:
            print(f"  analysed {n}/{len(todo)}", flush=True)
        if not mp3:
            continue
        a = speech.decode_audio(mp3)
        heard, pitch = speech.syllable_table(a, speech.transcribe(a))
        exp, _, spans = reading_tones_ex("".join(h["c"] for h in heard))
        if len(exp) != len(heard):
            continue
        breaks = {i for i, h in enumerate(heard) if h.get("brk")}
        tones = [e[1] for e in exp]
        surf = sandhi(tones, [e[0] for e in exp], breaks, spans)
        unsure = sandhi_optional(tones, breaks)  # either 2nd or 3rd is natural: leave out of training
        cache[it] = [(h["feat"], t) for i, (h, t) in enumerate(zip(heard, surf))
                     if h["feat"] is not None and t in (1, 2, 3, 4) and i not in unsure]
    pickle.dump(cache, open(cache_p, "wb"))

    # Per-utterance normalisation, exactly as at inference time.
    X, y, vs = [], [], []
    for it in items:
        rows = cache.get(it) or []
        if not rows:
            continue
        for f, (_, t) in zip(speech.normalize_utterance([f for f, _ in rows]), rows):
            X.append(f)
            y.append(t)
            vs.append(it[1])
    X = np.array(X, dtype=np.float32)
    y = np.array(y)
    vs = np.array(vs)
    print(f"{len(y)} syllables; class counts", {c: int((y == c).sum()) for c in (1, 2, 3, 4)})

    # Leave one voice out: accuracy, and how often a confident flag would be a false alarm / a catch.
    P = np.zeros((len(y), 4))
    for held in voices:
        mu, sd, nets = fit(X[vs != held], y[vs != held])
        P[vs == held] = predict(mu, sd, nets, X[vs == held])
    det = P.argmax(1) + 1
    p_exp = P[np.arange(len(y)), y - 1]
    for held in voices:
        m = vs == held
        fa = ((det != y) & (P.max(1) >= speech.SURE_DETECTED) & (p_exp <= speech.SURE_EXPECTED))[m].mean()
        print(f"held-out {held}: accuracy {np.mean(det[m] == y[m]):.3f}, false alarms {fa:.3f}")
    catches = []
    for t2 in (1, 2, 3, 4):  # pretend the target had been another tone: would we have flagged it?
        m = y != t2
        catches.append(((det[m] != t2) & (P.max(1)[m] >= speech.SURE_DETECTED) & (P[m, t2 - 1] <= speech.SURE_EXPECTED)).mean())
    print(f"wrong tones caught (simulated): {np.mean(catches):.3f}")

    mu, sd, nets = fit(X, y)
    model = {"type": "mlp", "classes": [1, 2, 3, 4], "mu": mu.tolist(), "sd": sd.tolist(),
             "nets": [[{"W": W.tolist(), "b": b.tolist()} for W, b in net] for net in nets]}
    (config.CONTENT_DIR / "tone_model.json").write_text(json.dumps(model))
    print("saved", config.CONTENT_DIR / "tone_model.json")


def fit(X, y, seeds=(0, 1, 2), epochs=60):
    """Three small MLPs (16 -> 96 -> 64 -> 4) whose probabilities are averaged."""
    import torch
    from torch import nn

    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = torch.tensor((X - mu) / sd, dtype=torch.float32)
    Y = torch.tensor(y - 1)
    nets = []
    for seed in seeds:
        torch.manual_seed(seed)
        net = nn.Sequential(nn.Linear(Z.shape[1], 96), nn.ReLU(), nn.Dropout(0.15), nn.Linear(96, 64), nn.ReLU(), nn.Linear(64, 4))
        opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-3)
        for _ in range(epochs):
            net.train()
            perm = torch.randperm(len(Z))
            for i in range(0, len(Z), 128):
                idx = perm[i:i + 128]
                opt.zero_grad()
                nn.functional.cross_entropy(net(Z[idx] + 0.05 * torch.randn_like(Z[idx])), Y[idx]).backward()
                opt.step()
        net.eval()
        nets.append([(m.weight.detach().numpy().astype(np.float64), m.bias.detach().numpy().astype(np.float64))
                     for m in net if isinstance(m, nn.Linear)])
    return mu, sd, nets


def predict(mu, sd, nets, X):
    Z = (X - mu) / sd
    total = np.zeros((len(Z), 4))
    for net in nets:
        h = Z
        for k, (W, b) in enumerate(net):
            h = h @ W.T + b
            if k < len(net) - 1:
                h = np.maximum(h, 0)
        e = np.exp(h - h.max(1, keepdims=True))
        total += e / e.sum(1, keepdims=True)
    return total / len(nets)


if __name__ == "__main__":
    main()
