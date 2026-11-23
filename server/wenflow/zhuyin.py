"""Pinyin <-> Zhuyin (bopomofo) conversion and the standard Daqian (大千) keyboard layout."""
from __future__ import annotations

import re
import unicodedata

INITIALS = {
    "b": "ㄅ", "p": "ㄆ", "m": "ㄇ", "f": "ㄈ",
    "d": "ㄉ", "t": "ㄊ", "n": "ㄋ", "l": "ㄌ",
    "g": "ㄍ", "k": "ㄎ", "h": "ㄏ",
    "j": "ㄐ", "q": "ㄑ", "x": "ㄒ",
    "zh": "ㄓ", "ch": "ㄔ", "sh": "ㄕ", "r": "ㄖ",
    "z": "ㄗ", "c": "ㄘ", "s": "ㄙ",
}

FINALS = {
    "a": "ㄚ", "o": "ㄛ", "e": "ㄜ", "ê": "ㄝ", "ai": "ㄞ", "ei": "ㄟ", "ao": "ㄠ", "ou": "ㄡ",
    "an": "ㄢ", "en": "ㄣ", "ang": "ㄤ", "eng": "ㄥ", "er": "ㄦ", "ong": "ㄨㄥ",
    "i": "ㄧ", "ia": "ㄧㄚ", "io": "ㄧㄛ", "ie": "ㄧㄝ", "iai": "ㄧㄞ", "iao": "ㄧㄠ", "iu": "ㄧㄡ",
    "iou": "ㄧㄡ", "ian": "ㄧㄢ", "in": "ㄧㄣ", "iang": "ㄧㄤ", "ing": "ㄧㄥ", "iong": "ㄩㄥ",
    "u": "ㄨ", "ua": "ㄨㄚ", "uo": "ㄨㄛ", "uai": "ㄨㄞ", "ui": "ㄨㄟ", "uei": "ㄨㄟ", "uan": "ㄨㄢ",
    "un": "ㄨㄣ", "uen": "ㄨㄣ", "uang": "ㄨㄤ", "ueng": "ㄨㄥ",
    "ü": "ㄩ", "üe": "ㄩㄝ", "üan": "ㄩㄢ", "ün": "ㄩㄣ",
}

Y_W = {
    "yi": "i", "ya": "ia", "yo": "io", "ye": "ie", "yai": "iai", "yao": "iao", "you": "iou",
    "yan": "ian", "yin": "in", "yang": "iang", "ying": "ing", "yong": "iong",
    "yu": "ü", "yue": "üe", "yuan": "üan", "yun": "ün",
    "wu": "u", "wa": "ua", "wo": "uo", "wai": "uai", "wei": "uei", "wan": "uan", "wen": "uen",
    "wang": "uang", "weng": "ueng",
}

SPECIAL = {"m": "ㄇ", "n": "ㄋ", "ng": "ㄫ", "hm": "ㄏㄇ", "hng": "ㄏㄫ", "r": "ㄦ", "e": "ㄜ", "ê": "ㄝ"}

TONE_MARKS = {1: "", 2: "ˊ", 3: "ˇ", 4: "ˋ", 5: "˙"}
MARK_TO_TONE = {"ˊ": 2, "ˇ": 3, "ˋ": 4, "˙": 5}

# Standard Daqian layout used by Microsoft Bopomofo, macOS Zhuyin, Gboard etc.
KEY_TO_ZHUYIN = {
    "1": "ㄅ", "q": "ㄆ", "a": "ㄇ", "z": "ㄈ",
    "2": "ㄉ", "w": "ㄊ", "s": "ㄋ", "x": "ㄌ",
    "e": "ㄍ", "d": "ㄎ", "c": "ㄏ",
    "r": "ㄐ", "f": "ㄑ", "v": "ㄒ",
    "5": "ㄓ", "t": "ㄔ", "g": "ㄕ", "b": "ㄖ",
    "y": "ㄗ", "h": "ㄘ", "n": "ㄙ",
    "u": "ㄧ", "j": "ㄨ", "m": "ㄩ",
    "8": "ㄚ", "i": "ㄛ", "k": "ㄜ", ",": "ㄝ",
    "9": "ㄞ", "o": "ㄟ", "l": "ㄠ", ".": "ㄡ",
    "0": "ㄢ", "p": "ㄣ", ";": "ㄤ", "/": "ㄥ", "-": "ㄦ",
    " ": "ˉ", "6": "ˊ", "3": "ˇ", "4": "ˋ", "7": "˙",
}
ZHUYIN_TO_KEY = {v: k for k, v in KEY_TO_ZHUYIN.items()}

_TONE_VOWELS = {
    "a": "āáǎà", "e": "ēéěè", "i": "īíǐì", "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ",
}
_MARKED = {c: (v, i + 1) for v, cs in _TONE_VOWELS.items() for i, c in enumerate(cs)}


def split_tone(syl: str) -> tuple[str, int]:
    """'hao3' -> ('hao', 3); 'hǎo' -> ('hao', 3); 'de' -> ('de', 5)."""
    syl = syl.strip().lower().replace("u:", "ü").replace("v", "ü")
    m = re.match(r"^([a-zü]+)([1-5])$", syl)
    if m:
        return m.group(1), int(m.group(2))
    tone = 5
    out = []
    for ch in unicodedata.normalize("NFC", syl):
        if ch in _MARKED:
            base, tone = _MARKED[ch]
            out.append(base)
        else:
            out.append(ch)
    return "".join(out), tone


def pinyin_to_zhuyin(syl: str) -> str:
    """Convert one pinyin syllable (numbered or tone-marked) to zhuyin with a tone mark."""
    base, tone = split_tone(syl)
    if not base or not re.match(r"^[a-zü]+$", base):
        return syl
    body = _body(base)
    if body is None:
        return syl
    mark = TONE_MARKS[tone]
    # Taiwan convention: the neutral-tone dot is written before the syllable.
    return f"˙{body}" if tone == 5 else body + mark


def _body(base: str) -> str | None:
    if base in ("zhi", "chi", "shi", "ri", "zi", "ci", "si"):
        return INITIALS[base[:-1]]
    if base in Y_W:
        return FINALS[Y_W[base]]
    if base in SPECIAL:
        return SPECIAL[base]
    for ini in ("zh", "ch", "sh"):
        if base.startswith(ini):
            return _with_initial(ini, base[2:])
    if base[0] in INITIALS:
        return _with_initial(base[0], base[1:])
    return FINALS.get(base) or SPECIAL.get(base)


def _with_initial(ini: str, fin: str) -> str | None:
    if ini in ("j", "q", "x") and fin.startswith("u"):
        fin = "ü" + fin[1:]
    if fin == "" and ini in ("m", "n"):
        return None
    f = FINALS.get(fin)
    if f is None:
        return None
    return INITIALS[ini] + f


def pinyin_num_to_marks(syl: str) -> str:
    """'hao3' -> 'hǎo'. Leaves already-marked or unparseable syllables unchanged."""
    base, tone = split_tone(syl)
    if tone == 5 or not base:
        return base or syl
    idx = -1
    if "a" in base:
        idx = base.index("a")
    elif "e" in base:
        idx = base.index("e")
    elif "ou" in base:
        idx = base.index("o")
    else:
        for i in range(len(base) - 1, -1, -1):
            if base[i] in "aeiouü":
                idx = i
                break
    if idx < 0:
        return base
    v = base[idx]
    return base[:idx] + _TONE_VOWELS[v][tone - 1] + base[idx + 1:]


def zhuyin_to_keys(zy: str) -> str:
    """'ㄋㄧˇ' -> 'su3'. Tone 1 is typed with space."""
    keys = []
    tone_mark = None
    for ch in zy:
        if ch == "˙":
            tone_mark = "7"
        elif ch in ZHUYIN_TO_KEY:
            keys.append(ZHUYIN_TO_KEY[ch])
    has_tone = any(ch in "ˊˇˋ" for ch in zy)
    if tone_mark:
        keys.append(tone_mark)
    elif not has_tone:
        keys.append(" ")
    return "".join(keys)


def syllable_tone(zy_or_py: str) -> int:
    if any(ch in MARK_TO_TONE for ch in zy_or_py):
        for ch in zy_or_py:
            if ch in MARK_TO_TONE:
                return MARK_TO_TONE[ch]
    if re.search(r"[ㄅ-ㄯ]", zy_or_py):
        return 1
    return split_tone(zy_or_py)[1]


def zhuyin_key(zy_syllables: list[str]) -> str:
    """Canonical IME lookup key: syllables joined, tone-1 shown as 'ˉ' and the neutral dot moved to the end."""
    out = []
    for s in zy_syllables:
        if s.startswith("˙"):
            out.append(s[1:] + "˙")
        elif s and s[-1] in "ˊˇˋ":
            out.append(s)
        else:
            out.append(s + "ˉ")
    return "".join(out)
