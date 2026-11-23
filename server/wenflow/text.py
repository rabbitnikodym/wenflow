"""Text processing: Traditional conversion, word segmentation and per-character pinyin/zhuyin annotation
with Taiwan-standard readings.

Readings come from g2pW (context-aware, trained on Taiwan Mandarin) when available, otherwise from
pypinyin + CC-CEDICT. Either way they pass through the same Taiwan post-processing:
curated word overrides, character-level Taiwan readings, and restoring full tones where Taiwan
does not use the neutral tone.
"""
from __future__ import annotations

import re
import threading
from functools import lru_cache

import jieba
import opencc
from pypinyin import Style, lazy_pinyin

from . import dictionary, g2p
from .content_store import taiwan_vocab
from .zhuyin import pinyin_num_to_marks, pinyin_to_zhuyin, split_tone  # noqa: F401 (split_tone re-exported)

_s2twp = opencc.OpenCC("s2twp")
_s2t = opencc.OpenCC("s2t")
_s2tw = opencc.OpenCC("s2tw")
_t2s = opencc.OpenCC("t2s")
HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_RUN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]+|[^㐀-䶿一-鿿豈-﫿]+")

# In Taiwan Mandarin most syllables keep their full tone where Beijing Mandarin uses the neutral tone
# (東西 dōngxī, 朋友 péngyǒu). These grammatical particles and suffixes stay neutral.
NEUTRAL_KEEP = set("的了嗎呢吧啊呀哪啦喔哦囉嘛著們子麼個得地么唄咧欸耶呵嘍兒哇")

# Character readings where the Taiwan standard differs from the mainland standard in every word.
CHAR_TW = {
    ("期", "qi1"): "qi2", ("危", "wei1"): "wei2", ("微", "wei1"): "wei2", ("企", "qi3"): "qi4",
    ("質", "zhi4"): "zhi2", ("綜", "zong1"): "zong4", ("寂", "ji4"): "ji2",
    ("擁", "yong1"): "yong3", ("髮", "fa4"): "fa3", ("跌", "die1"): "die2",
    ("昔", "xi1"): "xi2", ("惜", "xi1"): "xi2", ("息", "xi1"): "xi2", ("熄", "xi1"): "xi2",
    ("夕", "xi1"): "xi4", ("檔", "dang4"): "dang3", ("框", "kuang4"): "kuang1",
    ("垃", "la1"): "le4", ("圾", "ji1"): "se4", ("突", "tu1"): "tu2", ("擊", "ji1"): "ji2",
    ("績", "ji4"): "ji1", ("跡", "ji4"): "ji1", ("蹟", "ji4"): "ji1",
}

_init_lock = threading.Lock()
_initialized = False


def _init() -> None:
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        jieba.setLogLevel(60)
        jieba.initialize()
        for item in taiwan_vocab():
            w = item.get("trad", "")
            if 1 < len(w) <= 6 and all(HAN_RE.match(c) for c in w):
                jieba.add_word(_t2s.convert(w), freq=20000)
        _initialized = True


def is_simplified(text: str) -> bool:
    """Heuristic: more characters change under s->t than under t->s."""
    han = "".join(HAN_RE.findall(text))[:2000]
    if not han:
        return False
    to_t = sum(a != b for a, b in zip(han, _s2t.convert(han)))
    to_s = sum(a != b for a, b in zip(han, _t2s.convert(han)))
    return to_t > to_s


def to_traditional(text: str) -> str:
    """Simplified -> Traditional in Taiwan's standard character forms, word for word
    (裡, 為, 著, 麵, 台). Never swaps vocabulary, so it is safe for transcripts."""
    return _s2tw.convert(text).replace("臺", "台")


def localize(text: str) -> str:
    """Simplified mainland text -> Traditional with Taiwan phrasing (软件 -> 軟體, 视频 -> 影片)."""
    return _s2twp.convert(text).replace("臺", "台")


def ensure_traditional(text: str) -> str:
    return to_traditional(text) if is_simplified(text) else text


_PUNCT = {",": "，", "?": "？", "!": "！", ":": "：", ";": "；"}
_PUNCT_RE = re.compile(r"(?<=[㐀-鿿])\s*([,?!:;])\s*|\s*([,?!:;])\s*(?=[㐀-鿿])")


def fullwidth_punct(text: str) -> str:
    """Chinese punctuation for Chinese text: speech recognisers often emit ASCII commas."""
    return _PUNCT_RE.sub(lambda m: _PUNCT[m.group(1) or m.group(2)], text)


def to_simplified(text: str) -> str:
    return _t2s.convert(text)


def segment(text: str) -> list[str]:
    """Segment Traditional text. jieba's dictionary is simplified, so we segment a char-aligned
    simplified copy and map the boundaries back."""
    _init()
    simp = _t2s.convert(text)
    if len(simp) != len(text):
        simp = "".join(c2 if len(c2 := _t2s.convert(c)) == 1 else c for c in text)
    out, i = [], 0
    for tok in jieba.cut(simp, HMM=True):
        out.append(text[i:i + len(tok)])
        i += len(tok)
    return out


# ----------------------------------------------------------------------------------------------
# Readings
# ----------------------------------------------------------------------------------------------

def _norm(p: str) -> str:
    return p.lower().replace("u:", "ü").replace("v", "ü")


def _toneless(pys) -> list[str]:
    return [split_tone(p)[0] for p in pys]


@lru_cache(maxsize=50000)
def _entries(word: str) -> tuple:
    rows = dictionary._conn().execute(
        "SELECT pinyin, tw_pinyin, proper FROM entries WHERE trad=? ORDER BY proper, freq DESC", (word,)).fetchall()
    return tuple({"pinyin_main": r["pinyin"], "tw": r["tw_pinyin"]} for r in rows)


def _dict_reading(word: str) -> list[str]:
    """Context-free fallback: pypinyin phrase dictionary on the simplified form."""
    simp = _t2s.convert(word)
    if len(simp) != len(word):
        simp = word
    pys = lazy_pinyin(simp, style=Style.TONE3, neutral_tone_with_five=True, errors=lambda x: ["?"] * len(x))
    if len(pys) != len(word):
        pys = (pys + ["?"] * len(word))[: len(word)]
    return [_norm(p) for p in pys]


@lru_cache(maxsize=4096)
def _single(ch: str) -> str:
    r = lazy_pinyin(_t2s.convert(ch), style=Style.TONE3, neutral_tone_with_five=True)
    return _norm(r[0]) if r else "?"


@lru_cache(maxsize=100000)
def _finalize(word: str, base: tuple) -> tuple[tuple[str, ...], tuple[str | None, ...]]:
    """Taiwan post-processing of one word's readings.
    Returns (display readings, citation readings where they differ else None)."""
    pys = list(base)
    # 1. Whole-word Taiwan readings from the dictionary (curated list + CC-CEDICT 'Taiwan pr.').
    tl = _toneless(pys)
    for e in _entries(word):
        if not e["tw"]:
            continue
        tw = e["tw"].split()
        if len(tw) != len(word):
            continue
        if _toneless(e["pinyin_main"].split()) == tl or _toneless(tw) == tl or len(_entries(word)) == 1:
            pys = [_norm(p) for p in tw]
            break
    # 2. Characters that are read differently in Taiwan in every word.
    pys = [CHAR_TW.get((ch, p), p) for ch, p in zip(word, pys)]
    # 3. Taiwan keeps full tones outside particles, suffixes and reduplication.
    out = []
    for i, (ch, p) in enumerate(zip(word, pys)):
        if p.endswith("5") and ch not in NEUTRAL_KEEP and not (i > 0 and word[i - 1] == ch):
            s = _single(ch)
            if s != "?" and not s.endswith("5") and split_tone(s)[0] == split_tone(p)[0]:
                p = CHAR_TW.get((ch, s), s)
        out.append(p)
    # 4. 一 and 不 are typed in their citation tone whatever their surface tone is.
    cite: list[str | None] = [None] * len(out)
    for i, (ch, p) in enumerate(zip(word, out)):
        if ch == "一" and p in ("yi2", "yi4"):
            cite[i] = "yi1"
        elif ch == "不" and p == "bu2":
            cite[i] = "bu4"
    return tuple(out), tuple(cite)


def _apply_yi_bu(chars: list[str], pys: list[str]) -> list[str]:
    """Surface tones of 一 and 不 by rule, for the fallback path (the model already predicts them)."""
    out = list(pys)
    for i, ch in enumerate(chars):
        nxt = split_tone(out[i + 1])[1] if i + 1 < len(out) and out[i + 1] not in ("?", "") else 0
        if ch == "不" and out[i] == "bu4" and nxt == 4:
            out[i] = "bu2"
        elif ch == "一" and out[i] == "yi1" and nxt and not (i > 0 and chars[i - 1] in "第十初"):
            if i + 1 < len(chars) and chars[i + 1] in "月日號點、，。":
                continue
            out[i] = "yi2" if nxt == 4 else "yi4"
    return out


def _base_readings(text: str) -> list[str | None]:
    """One reading per character of `text` (None for non-Han), before word-level post-processing."""
    r = g2p.readings(text)
    if r is not None and len(r) == len(text):
        return r
    return [None] * len(text)


def _word_reading(word: str) -> tuple[str, ...]:
    """Numbered pinyin per character for a stand-alone word, Taiwan-preferred."""
    return _readings_for(word, _base_readings(word))[0]


def _readings_for(word: str, base: list[str | None]) -> tuple[tuple[str, ...], tuple[str | None, ...]]:
    if any(b is None for b in base):
        fb = _apply_yi_bu(list(word), _dict_reading(word))
        base = [b or f for b, f in zip(base, fb)]
    return _finalize(word, tuple(base))


@lru_cache(maxsize=50000)
def _gloss(word: str) -> tuple[str, int | None, int]:
    hits = dictionary.lookup(word)
    if not hits:
        return "", None, 0
    h = hits[0]
    defs = [d for d in h["defs"] if not d.startswith(("variant of", "old variant", "CL:", "surname "))] or h["defs"]
    g = "; ".join(defs[:2])
    g = re.sub(r"\[[^\]]*\]", "", re.sub(r"([㐀-鿿]+)\|[㐀-鿿]+", r"\1", g))
    return g[:90], next((x["hsk"] for x in hits if x["hsk"]), None), h["freq"]


def annotate(text: str, with_gloss: bool = True) -> list[dict]:
    """Tokens for display: {w, han, chars:[{c, py, zy, t, (cz)}], g, hsk, f}.
    `zy`/`py`/`t` are what is said (一 and 不 with tone sandhi); `cz` is the citation zhuyin to type,
    present only when it differs. Non-Han text is passed through as {w, han: False}."""
    if not text:
        return []
    base = _base_readings(text)
    tokens: list[dict] = []
    pos = 0
    for w in segment(text):
        start = pos
        pos += len(w)
        if not HAN_RE.search(w):
            tokens.append({"w": w, "han": False})
            continue
        off = start
        for part in _RUN_RE.findall(w):
            if not HAN_RE.match(part[0]):
                tokens.append({"w": part, "han": False})
                off += len(part)
                continue
            pys, cite = _readings_for(part, base[off:off + len(part)])
            off += len(part)
            chars = []
            for c, p, cz in zip(part, pys, cite):
                if p == "?":
                    chars.append({"c": c, "py": "", "zy": "", "t": 0})
                    continue
                rec = {"c": c, "py": pinyin_num_to_marks(p), "zy": pinyin_to_zhuyin(p), "t": split_tone(p)[1]}
                if cz:
                    rec["cz"] = pinyin_to_zhuyin(cz)
                chars.append(rec)
            tok = {"w": part, "han": True, "chars": chars}
            if with_gloss:
                g, hsk, f = _gloss(part)
                tok.update({"g": g, "hsk": hsk, "f": f})
            tokens.append(tok)
    return tokens


def annotate_many(texts: list[str], with_gloss: bool = False) -> list[list[dict]]:
    """Annotate many short texts (caption lines) with one batched model call."""
    g2p.readings_many([t for t in texts if t])
    return [annotate(t, with_gloss) for t in texts]


def reading_tones(text: str) -> list[tuple[str, int, str]]:
    """(char, spoken tone before 3rd-tone sandhi, pinyin) for each Han character."""
    return reading_tones_ex(text)[0]


def reading_tones_ex(text: str) -> tuple[list[tuple[str, int, str]], set[int], list[tuple[int, int]]]:
    """Like reading_tones, plus (a) the indices (into the Han characters) where a new phrase starts
    after punctuation — third-tone sandhi does not cross those — and (b) the word spans."""
    out: list[tuple[str, int, str]] = []
    breaks: set[int] = set()
    spans: list[tuple[int, int]] = []
    pending = False
    for tok in annotate(text, with_gloss=False):
        if tok["han"]:
            if pending and out:
                breaks.add(len(out))
            pending = False
            start = len(out)
            for ch in tok["chars"]:
                out.append((ch["c"], ch["t"], ch["py"]))
            spans.append((start, len(out)))
        elif tok["w"].strip():
            pending = True
    return out, breaks, spans


def sandhi(tones: list[int], chars: list[str], breaks: set[int] | None = None,
           spans: list[tuple[int, int]] | None = None) -> list[int]:
    """Surface tones after third-tone sandhi.

    Inside a word every third tone before another third tone becomes a second tone (老闆 2-3,
    展覽館 2-2-3). Across words, a one-syllable word does the same before a following third tone,
    working from the right (我也很好 -> 2-3-2-3). Phrase breaks (`breaks`) block it.
    一 / 不 sandhi is already part of the readings."""
    out = list(tones)
    brk = breaks or set()
    n = len(out)
    spans = spans or [(i, i + 1) for i in range(n)]
    for a, b in spans:
        for i in range(b - 2, a - 1, -1):
            if tones[i] == 3 and tones[i + 1] == 3:
                out[i] = 2
    for k in range(len(spans) - 2, -1, -1):
        a, b = spans[k]
        if b - a == 1 and b < n and b not in brk and out[a] == 3 and out[b] == 3:
            out[a] = 2
    return out


def sandhi_optional(tones: list[int], breaks: set[int] | None = None) -> set[int]:
    """Indices where both a second and a third tone are natural: any third tone directly before
    another third tone in the same phrase (how far sandhi spreads depends on speed and phrasing)."""
    brk = breaks or set()
    return {i for i in range(len(tones) - 1) if tones[i] == 3 and tones[i + 1] == 3 and (i + 1) not in brk}


_NUMERIC = set("零〇一二三四五六七八九十百千萬億兩半第年月日號點分秒個幾多")
_PARTICLES = set("喔啦耶欸齁咧嘛囉哇嘿嗨呃嗯哦唉噢啊呀吧呢嗎哎唷蛤捏吼厚")
_kc: tuple[int, set[str]] = (0, set())


def _known_chars(known: set[str]) -> set[str]:
    global _kc
    if _kc[0] != len(known):
        _kc = (len(known), {c for w in known for c in w})
    return _kc[1]


def is_known(w: str, known: set[str]) -> bool:
    """Would this learner understand the word? Listed words, plus transparent common compounds of
    characters they know (今年, 出門, 要不要), numbers and dates."""
    if w in known or all(c in _NUMERIC or c in _PARTICLES for c in w):
        return True
    f, h = dictionary.word_info(w)
    if h and h <= 3:
        return True
    f = max(f, jieba.dt.FREQ.get(_t2s.convert(w), 0) or 0)  # phrases the segmenter knows but the dictionary lacks
    kc = _known_chars(known)
    if len(w) == 1:
        return w in kc or f > 20000
    if len(w) <= 4 and len(set(w)) == 1 and w[0] in kc:  # 慢慢, 謝謝
        return True
    return len(w) <= 4 and f >= 100 and all(c in kc or c in _PARTICLES for c in w)


def word_difficulty(words: list[str], known: set[str]) -> dict:
    """Coverage-based difficulty: the share of running words the learner knows, the words they do not,
    and a 1-7 level derived from the coverage (98% reads comfortably, below 85% is a struggle)."""
    han = [w for w in words if HAN_RE.search(w)]
    if not han:
        return {"coverage": 1.0, "level": 1, "unknown": []}
    verdict: dict[str, bool] = {}
    unknown = []
    for w in han:
        if w not in verdict:
            verdict[w] = is_known(w, known)
        if not verdict[w]:
            unknown.append(w)
    cov = 1 - len(unknown) / len(han)
    lvl = 2 if cov >= 0.985 else 3 if cov >= 0.965 else 4 if cov >= 0.94 else 5 if cov >= 0.91 else 6 if cov >= 0.86 else 7
    counts: dict[str, int] = {}
    for w in unknown:
        counts[w] = counts.get(w, 0) + 1
    uniq = sorted(counts, key=lambda w: -counts[w])
    return {"coverage": round(cov, 3), "level": lvl, "unknown": uniq[:200]}
