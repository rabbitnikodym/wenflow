"""The zhuyin (bopomofo) course: 22 units from the first symbols to timed typing on the 大千 layout.

Units carry hand-written teaching notes; drills are generated from the symbols learned so far, using
real words the learner already knows (HSK 1-5) in Traditional characters.
"""
from __future__ import annotations

import random
import re
from functools import lru_cache

from . import db, decks
from .zhuyin import KEY_TO_ZHUYIN, ZHUYIN_TO_KEY, zhuyin_to_keys

# symbol, pinyin, example char, example reading, mnemonic
SYMBOLS: dict[str, dict] = {}


# How each symbol is named when the chart is recited: initials take ㄛ, ㄜ or ㄧ; the rest are their own sound.
NAMES = {
    "ㄅ": "bo", "ㄆ": "po", "ㄇ": "mo", "ㄈ": "fo", "ㄉ": "de", "ㄊ": "te", "ㄋ": "ne", "ㄌ": "le",
    "ㄍ": "ge", "ㄎ": "ke", "ㄏ": "he", "ㄐ": "ji", "ㄑ": "qi", "ㄒ": "xi",
    "ㄓ": "zhi", "ㄔ": "chi", "ㄕ": "shi", "ㄖ": "ri", "ㄗ": "zi", "ㄘ": "ci", "ㄙ": "si",
    "ㄧ": "yi", "ㄨ": "wu", "ㄩ": "yu", "ㄚ": "a", "ㄛ": "o", "ㄜ": "e", "ㄝ": "ê",
    "ㄞ": "ai", "ㄟ": "ei", "ㄠ": "ao", "ㄡ": "ou", "ㄢ": "an", "ㄣ": "en", "ㄤ": "ang", "ㄥ": "eng", "ㄦ": "er",
}
# An everyday word that starts with (or clearly contains) the symbol, heard in a natural phrase.
WORDS = {
    "ㄅ": ("爸爸", "bà ba"), "ㄆ": ("朋友", "péng yǒu"), "ㄇ": ("媽媽", "mā ma"), "ㄈ": ("方便", "fāng biàn"),
    "ㄉ": ("弟弟", "dì di"), "ㄊ": ("台灣", "tái wān"), "ㄋ": ("你好", "nǐ hǎo"), "ㄌ": ("老師", "lǎo shī"),
    "ㄍ": ("哥哥", "gē ge"), "ㄎ": ("可以", "kě yǐ"), "ㄏ": ("好吃", "hǎo chī"),
    "ㄐ": ("今天", "jīn tiān"), "ㄑ": ("請問", "qǐng wèn"), "ㄒ": ("謝謝", "xiè xie"),
    "ㄓ": ("知道", "zhī dào"), "ㄔ": ("吃飯", "chī fàn"), "ㄕ": ("什麼", "shén me"), "ㄖ": ("日本", "rì běn"),
    "ㄗ": ("再見", "zài jiàn"), "ㄘ": ("廁所", "cè suǒ"), "ㄙ": ("四十", "sì shí"),
    "ㄧ": ("一起", "yì qǐ"), "ㄨ": ("五月", "wǔ yuè"), "ㄩ": ("下雨", "xià yǔ"),
    "ㄚ": ("大家", "dà jiā"), "ㄛ": ("我們", "wǒ men"), "ㄜ": ("可樂", "kě lè"), "ㄝ": ("姐姐", "jiě jie"),
    "ㄞ": ("可愛", "kě ài"), "ㄟ": ("妹妹", "mèi mei"), "ㄠ": ("早安", "zǎo ān"), "ㄡ": ("走路", "zǒu lù"),
    "ㄢ": ("晚安", "wǎn ān"), "ㄣ": ("很好", "hěn hǎo"), "ㄤ": ("幫忙", "bāng máng"), "ㄥ": ("冷氣", "lěng qì"),
    "ㄦ": ("兒子", "ér zi"),
}


def _s(sym, py, _ex, _ex_py, hint):
    word, word_py = WORDS[sym]
    SYMBOLS[sym] = {"sym": sym, "pinyin": py, "name": NAMES[sym], "key": ZHUYIN_TO_KEY[sym], "ex": word,
                    "ex_py": word_py, "hint": hint}


_s("ㄅ", "b", "爸", "bà", "From 勹, the wrapper in 包 (bāo).")
_s("ㄆ", "p", "怕", "pà", "From 攵 (pū, 'to tap') — the right side of 放.")
_s("ㄇ", "m", "媽", "mā", "From 冂/冖, a cover (mì). Looks like a doorway: mén.")
_s("ㄈ", "f", "飯", "fàn", "From 匚 (fāng), a box on its side.")
_s("ㄉ", "d", "大", "dà", "From 刀 (dāo), knife.")
_s("ㄊ", "t", "他", "tā", "From an old form of 突 (tú); think of a T with a tail.")
_s("ㄋ", "n", "你", "nǐ", "From 乃 (nǎi).")
_s("ㄌ", "l", "來", "lái", "From 力 (lì), strength.")
_s("ㄍ", "g", "高", "gāo", "From 巜, an old character for a stream (guì).")
_s("ㄎ", "k", "看", "kàn", "From 丂, the bottom of 考 (kǎo).")
_s("ㄏ", "h", "好", "hǎo", "From 厂 (hǎn), a cliff.")
_s("ㄐ", "j", "家", "jiā", "From 丩, the right side of 叫 (jiào).")
_s("ㄑ", "q", "去", "qù", "From 𡿨 (quǎn), a small stream — one bent stroke.")
_s("ㄒ", "x", "小", "xiǎo", "From 丅, an old form of 下 (xià).")
_s("ㄓ", "zh", "中", "zhōng", "From 㞢, the old form of 之 (zhī).")
_s("ㄔ", "ch", "吃", "chī", "From 彳 (chì), the 'step' radical in 行 and 很.")
_s("ㄕ", "sh", "是", "shì", "From 尸 (shī).")
_s("ㄖ", "r", "日", "rì", "From 日 (rì) itself.")
_s("ㄗ", "z", "在", "zài", "From 卩, the old form of 節 (once read with a z- sound).")
_s("ㄘ", "c", "次", "cì", "From 七 (qī) — anciently a ts- sound.")
_s("ㄙ", "s", "四", "sì", "From 厶 (sī), the old form of 私.")
_s("ㄧ", "i / y-", "一", "yī", "From 一 (yī). Horizontal in vertical text, vertical in horizontal text.")
_s("ㄨ", "u / w-", "五", "wǔ", "From 㐅, the old form of 五 (wǔ).")
_s("ㄩ", "ü / yu-", "魚", "yú", "From 凵 (qū), an open container.")
_s("ㄚ", "a", "啊", "a", "From 丫 (yā), a fork.")
_s("ㄛ", "o", "喔", "ō", "From an old form of 呵 (hē/ō).")
_s("ㄜ", "e", "餓", "è", "ㄛ with a nick in the top stroke: the same vowel family, unrounded.")
_s("ㄝ", "ê (ie, üe)", "也", "yě", "From 也 (yě). Almost always follows ㄧ or ㄩ.")
_s("ㄞ", "ai", "愛", "ài", "From an old form of 亥 (hài).")
_s("ㄟ", "ei", "給", "gěi", "From 乁 (yí), a flowing stroke.")
_s("ㄠ", "ao", "要", "yào", "From 幺 (yāo), the top of 么.")
_s("ㄡ", "ou", "有", "yǒu", "From 又 (yòu).")
_s("ㄢ", "an", "安", "ān", "From an old character read hàn.")
_s("ㄣ", "en", "很", "hěn", "From 乚, the old form of 隱 (yǐn).")
_s("ㄤ", "ang", "忙", "máng", "From 尢 (wāng).")
_s("ㄥ", "eng", "冷", "lěng", "From an old form of 肱 (gōng).")
_s("ㄦ", "er", "二", "èr", "From 儿 (ér), the Simplified 儿 itself.")

INITIALS = "ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙ"
MEDIALS = "ㄧㄨㄩ"
FINALS = "ㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦ"
TONES = "ˊˇˋ˙"

KEYBOARD_ROWS = ["1234567890-", "qwertyuiop", "asdfghjkl;", "zxcvbnm,./"]

COMPOUNDS = [
    ("ㄧㄚ", "ia / ya", "家 ㄐㄧㄚ"), ("ㄧㄝ", "ie / ye", "謝 ㄒㄧㄝˋ"), ("ㄧㄠ", "iao / yao", "小 ㄒㄧㄠˇ"),
    ("ㄧㄡ", "iu / you", "九 ㄐㄧㄡˇ"), ("ㄧㄢ", "ian / yan", "天 ㄊㄧㄢ"), ("ㄧㄣ", "in / yin", "新 ㄒㄧㄣ"),
    ("ㄧㄤ", "iang / yang", "想 ㄒㄧㄤˇ"), ("ㄧㄥ", "ing / ying", "聽 ㄊㄧㄥ"),
    ("ㄨㄚ", "ua / wa", "花 ㄏㄨㄚ"), ("ㄨㄛ", "uo / wo", "我 ㄨㄛˇ"), ("ㄨㄞ", "uai / wai", "快 ㄎㄨㄞˋ"),
    ("ㄨㄟ", "ui / wei", "對 ㄉㄨㄟˋ"), ("ㄨㄢ", "uan / wan", "晚 ㄨㄢˇ"), ("ㄨㄣ", "un / wen", "問 ㄨㄣˋ"),
    ("ㄨㄤ", "uang / wang", "黃 ㄏㄨㄤˊ"), ("ㄨㄥ", "ong / weng", "東 ㄉㄨㄥ"),
    ("ㄩㄝ", "üe / yue", "學 ㄒㄩㄝˊ"), ("ㄩㄢ", "üan / yuan", "遠 ㄩㄢˇ"), ("ㄩㄣ", "ün / yun", "雲 ㄩㄣˊ"),
    ("ㄩㄥ", "iong / yong", "用 ㄩㄥˋ"),
]
# The bare sound of each compound, as a first-tone character the voice reads exactly that way.
COMPOUND_SOUND = {
    "ㄧㄚ": "鴨", "ㄧㄝ": "耶", "ㄧㄠ": "腰", "ㄧㄡ": "優", "ㄧㄢ": "煙", "ㄧㄣ": "因", "ㄧㄤ": "央", "ㄧㄥ": "英",
    "ㄨㄚ": "蛙", "ㄨㄛ": "窩", "ㄨㄞ": "歪", "ㄨㄟ": "威", "ㄨㄢ": "彎", "ㄨㄣ": "溫", "ㄨㄤ": "汪", "ㄨㄥ": "翁",
    "ㄩㄝ": "約", "ㄩㄢ": "冤", "ㄩㄣ": "暈", "ㄩㄥ": "庸",
}


def compounds(first: str = "ㄧㄨㄩ") -> list[dict]:
    return [{"zy": z, "pinyin": p, "ex": e, "sound": COMPOUND_SOUND[z]} for z, p, e in COMPOUNDS if z[0] in first]


def _unit(n, title, zh, new, sections, drills, goal=""):
    return {"n": n, "title": title, "title_zh": zh, "new": list(new), "sections": sections, "drills": drills, "goal": goal}


UNITS = [
    _unit(1, "What zhuyin is · ㄅㄆㄇㄈ + ㄚ", "注音是什麼", "ㄅㄆㄇㄈㄚ", [
        {"h": "Why zhuyin", "body":
            "注音符號 (zhùyīn fúhào), nicknamed ㄅㄆㄇㄈ 'bopomofo', is how everyone in Taiwan learns to read and how "
            "most people type. It has 37 symbols and 4 tone marks. You already know every sound: zhuyin is just a "
            "different, more compact spelling of the syllables you spell in pinyin. A syllable is never longer than "
            "three symbols plus a tone: initial + medial + final. 你好 is ㄋㄧˇ ㄏㄠˇ."},
        {"h": "Three slots", "body":
            "Initial (聲母): 21 consonants, ㄅ to ㄙ. Medial (介音): ㄧ ㄨ ㄩ. Final (韻母): 13 vowels and endings, ㄚ to ㄦ. "
            "A whole ending like 'ang' or 'ou' is ONE symbol, which is why zhuyin is shorter than pinyin."},
        {"h": "The keyboard follows the chart", "body":
            "On the standard 大千 (Dàqiān) layout the symbols run down the keyboard in chart order, one column per "
            "group. ㄅㄆㄇㄈ is the first column: 1 Q A Z. Learn each group together with its column and you will "
            "never need to hunt for a key."},
        {"h": "Today: the lips, and a first vowel", "body": "ㄅ b, ㄆ p, ㄇ m, ㄈ f. When named aloud they take the vowel ㄛ: bo, po, mo, fo "
            "(tap a symbol to hear its name; in Taiwanese classrooms you will also hear a lighter 'bə pə mə fə' when sounds are blended). "
            "You also get your first vowel, ㄚ a (key 8, right hand), so you can read real syllables from day one: "
            "ㄅㄚˋ 爸, ㄇㄚ 媽, ㄆㄚˋ 怕, ㄈㄚˇ 法. Tone marks look the same as in pinyin and go after the syllable; first tone has none."},
    ], ["match", "keys", "spell"], "Read and type ㄅㄆㄇㄈ"),
    _unit(2, "ㄉㄊㄋㄌ + ㄧ", "舌尖音", "ㄉㄊㄋㄌㄧ", [
        {"h": "Second column: 2 W S X", "body":
            "ㄉ d, ㄊ t, ㄋ n, ㄌ l — the tongue-tip sounds. Named aloud with ㄜ: de, te, ne, le. "
            "ㄉ is a knife 刀 (dāo); ㄌ is 力 (lì); ㄋ is 乃 (nǎi). New vowel: ㄧ i (key U) — 你 ㄋㄧˇ, 地 ㄉㄧˋ, 力 ㄌㄧˋ."},
        {"h": "Reading a syllable", "body":
            "Read left to right (or top to bottom in ruby): initial, then the rest, then the tone mark. "
            "ㄉㄚˋ = d + a + 4th tone = 大. First tone has no mark."},
    ], ["match", "keys", "spell"], "Add the tongue-tip initials"),
    _unit(3, "ㄍㄎㄏ + ㄨ", "舌根音", "ㄍㄎㄏㄨ", [
        {"h": "Third column: E D C", "body":
            "ㄍ g, ㄎ k, ㄏ h. From here on columns have three keys, so the top number row is skipped: E, D, C. "
            "New vowel: ㄨ u (key J) — 不 ㄅㄨˋ, 路 ㄌㄨˋ, 哭 ㄎㄨ, 五 ㄨˇ."},
        {"h": "Look-alikes", "body": "ㄎ (k) has a hook at the bottom; ㄏ (h) is a cliff 厂; ㄍ (g) is two bent strokes."},
    ], ["match", "keys", "spell"], "Add g k h"),
    _unit(4, "ㄐㄑㄒ + ㄩ", "舌面音", "ㄐㄑㄒㄩ", [
        {"h": "Fourth column: R F V", "body":
            "ㄐ j, ㄑ q, ㄒ x. They are always followed by ㄧ or ㄩ, exactly as j q x are always followed by i or ü in pinyin. "
            "New vowel: ㄩ ü (key M) — 去 ㄑㄩˋ, 女 ㄋㄩˇ, 魚 ㄩˊ."},
        {"h": "No hidden ü", "body":
            "Pinyin writes ju, qu, xu but means jü, qü, xü. Zhuyin never hides it: 去 is ㄑㄩˋ, 學 is ㄒㄩㄝˊ. "
            "If you ever wondered why 'xu' and 'shu' have different vowels, zhuyin makes it obvious."},
    ], ["match", "keys", "spell"], "Add j q x"),
    _unit(5, "ㄓㄔㄕㄖ + ㄜ", "翹舌音", "ㄓㄔㄕㄖㄜ", [
        {"h": "Fifth column: 5 T G B", "body": "ㄓ zh, ㄔ ch, ㄕ sh, ㄖ r. One symbol each where pinyin needs two letters. "
            "New vowel: ㄜ e (key K) — 車 ㄔㄜ, 這 ㄓㄜˋ, 熱 ㄖㄜˋ, 喝 ㄏㄜ, and the neutral-tone 的 ˙ㄉㄜ and 了 ˙ㄌㄜ."},
        {"h": "They stand alone", "body":
            "In pinyin zhi, chi, shi, ri end in a dummy 'i'. Zhuyin writes just the consonant: 是 = ㄕˋ, 吃 = ㄔ, 日 = ㄖˋ, 知 = ㄓ. "
            "On the keyboard you type the symbol and then the tone key straight away."},
        {"h": "The Taiwanese accent", "body":
            "In relaxed Taiwan speech ㄓㄔㄕ are much less curled than in Beijing and often drift toward ㄗㄘㄙ. "
            "You still have to know which is which to type the word, so learn the standard contrast."},
    ], ["match", "keys", "spell"], "Add zh ch sh r"),
    _unit(6, "ㄗㄘㄙ · all 21 initials", "平舌音與聲母總複習", "ㄗㄘㄙ", [
        {"h": "Sixth column: Y H N", "body": "ㄗ z, ㄘ c, ㄙ s. Like ㄓㄔㄕㄖ they can stand alone: 字 = ㄗˋ, 次 = ㄘˋ, 四 = ㄙˋ."},
        {"h": "The left hand is done", "body":
            "That is all 21 initials: six columns, 1QAZ 2WSX EDC RFV 5TGB YHN. Chant them in order — "
            "ㄅㄆㄇㄈ ㄉㄊㄋㄌ ㄍㄎㄏ ㄐㄑㄒ ㄓㄔㄕㄖ ㄗㄘㄙ — it is the Taiwanese alphabet song and the order of every dictionary."},
    ], ["match", "keys", "spell", "type"], "Know all 21 initials and their keys"),
    _unit(7, "ㄧㄨㄩ as medials · ㄛ", "介音", "ㄛ", [
        {"h": "Seventh column: U J M", "body":
            "You already use ㄧ i, ㄨ u and ㄩ ü as vowels (一 ㄧ, 五 ㄨˇ, 魚 ㄩˊ). Their second job is the middle slot, "
            "before another final: 家 ㄐㄧㄚ, 花 ㄏㄨㄚ. New vowel: ㄛ o (key I), which mostly follows ㄨ — 我 ㄨㄛˇ, 多 ㄉㄨㄛ, 國 ㄍㄨㄛˊ."},
        {"h": "No y and no w", "body":
            "Pinyin's y and w are only spelling conventions for syllables that start with ㄧ ㄨ ㄩ. "
            "yi = ㄧ, wu = ㄨ, yu = ㄩ, ya = ㄧㄚ, wo = ㄨㄛ, yue = ㄩㄝ. There is nothing extra to type."},
    ], ["match", "keys", "spell", "type"], "Add the three medials"),
    _unit(8, "ㄝ and the vowel column", "單韻母", "ㄝ", [
        {"h": "Eighth column: 8 I K ,", "body": "ㄚ a, ㄛ o, ㄜ e, ㄝ ê run down one column of the right hand. Only ㄝ (the comma key) is new."},
        {"h": "Two kinds of e", "body":
            "Pinyin uses one letter 'e' for two sounds. ㄜ is the e of 餓 è, 喝 hē, 的 de. ㄝ is the e of 也 yě, 謝 xiè, 學 xué — "
            "it only appears after ㄧ or ㄩ."},
        {"h": "bo po mo fo", "body": "After ㄅㄆㄇㄈ pinyin 'o' is ㄛ: 波 ㄅㄛ, 佛 ㄈㄛˊ. Everywhere else pinyin 'uo' is ㄨㄛ: 多 ㄉㄨㄛ."},
    ], ["match", "keys", "spell", "type"], "Add a o e ê"),
    _unit(9, "ㄞㄟㄠㄡ", "複韻母", "ㄞㄟㄠㄡ", [
        {"h": "Ninth column: 9 O L .", "body": "ㄞ ai, ㄟ ei, ㄠ ao, ㄡ ou. Each two-letter pinyin ending is a single key."},
        {"h": "Look-alikes", "body": "ㄠ (ao) is the top of 么; ㄡ (ou) is 又. ㄞ (ai) has a foot; ㄟ (ei) is one flowing stroke."},
    ], ["match", "keys", "spell", "type"], "Add ai ei ao ou"),
    _unit(10, "ㄢㄣㄤㄥㄦ", "鼻韻母與ㄦ", "ㄢㄣㄤㄥㄦ", [
        {"h": "Tenth column: 0 P ; / and -", "body": "ㄢ an, ㄣ en, ㄤ ang, ㄥ eng, and ㄦ er on the minus key. That completes all 37 symbols."},
        {"h": "No 兒化", "body":
            "Taiwan Mandarin almost never adds 兒 to words: 一點 not 一點兒, 哪裡 not 哪兒, 玩 not 玩兒. "
            "ㄦ is used for 二, 兒子, 而且, 耳朵 and little else."},
        {"h": "ㄣ and ㄥ in Taiwan", "body":
            "Many Taiwanese merge -in/-ing and -en/-eng in speech, so you will hear 'yīn gāi' for 應該. "
            "The typing still needs the dictionary final, which is why natives sometimes hesitate over ㄣ or ㄥ too."},
    ], ["match", "keys", "spell", "type"], "All 37 symbols"),
    _unit(11, "Compound finals with ㄧ", "結合韻：ㄧ", "", [
        {"h": "Medial + final", "body":
            "ㄧ combines with a final to make ia, ie, iao, iu, ian, in, iang, ing. Type them in order: 想 = ㄒ ㄧ ㄤ ˇ."},
        {"h": "Pinyin traps", "body":
            "iu is really i+ou: 九 = ㄐㄧㄡˇ. in is ㄧㄣ and ing is ㄧㄥ. ian is ㄧㄢ even though it sounds like 'yen'. "
            "ye/ie is ㄧㄝ, not ㄧㄜ."},
    ], ["compound", "spell", "type"], "Spell ㄧ-compounds without thinking in pinyin"),
    _unit(12, "Compound finals with ㄨ and ㄩ", "結合韻：ㄨ、ㄩ", "", [
        {"h": "ㄨ compounds", "body":
            "ua, uo, uai, ui, uan, un, uang, ong. Traps: ui is u+ei → 對 ㄉㄨㄟˋ; un is u+en → 春 ㄔㄨㄣ; "
            "ong is u+eng → 東 ㄉㄨㄥ (and weng is the same ㄨㄥ)."},
        {"h": "ㄩ compounds", "body":
            "üe, üan, ün, and iong. yuan = ㄩㄢ, yun = ㄩㄣ, yue = ㄩㄝ. The surprise is iong: it is ㄩㄥ, so 用 = ㄩㄥˋ and 窮 = ㄑㄩㄥˊ."},
        {"h": "After ㄐㄑㄒ", "body": "ju/qu/xu, juan/quan/xuan, jun/qun/xun and jue/que/xue all use ㄩ: 全 ㄑㄩㄢˊ, 軍 ㄐㄩㄣ, 選 ㄒㄩㄢˇ."},
    ], ["compound", "spell", "type"], "Spell every final"),
    _unit(13, "Tones and tone keys", "聲調與調號", "", [
        {"h": "Five tones, four marks", "body":
            "First tone is unmarked. ˊ second, ˇ third, ˋ fourth — the same shapes as pinyin, written after the syllable "
            "(to its upper right in ruby). The neutral tone is a dot ˙ written BEFORE the syllable: 的 = ˙ㄉㄜ, 嗎 = ˙ㄇㄚ."},
        {"h": "Tone keys", "body":
            "The tone ends the syllable and tells the input method to convert it. Space = first tone, 6 = ˊ, 3 = ˇ, 4 = ˋ, "
            "7 = ˙. So 好 is C L 3 and 媽 is A 8 Space. Every syllable ends with a tone key — that rhythm is the heart of zhuyin typing."},
        {"h": "Fewer neutral tones", "body":
            "Taiwan keeps full tones where Beijing goes neutral: 東西 ㄉㄨㄥ ㄒㄧ, 朋友 ㄆㄥˊ ㄧㄡˇ, 知道 ㄓ ㄉㄠˋ, 漂亮 ㄆㄧㄠˋ ㄌㄧㄤˋ. "
            "Only particles and suffixes stay neutral: 的 了 嗎 呢 吧 們 子 著."},
    ], ["tones", "spell", "type"], "Type any syllable with its tone"),
    _unit(14, "Spelling rules that differ from pinyin", "拼寫規則", "", [
        {"h": "A checklist for pinyin brains", "body":
            "1. zhi chi shi ri zi ci si → the bare consonant. 2. y/w → ㄧ ㄨ ㄩ with nothing added. "
            "3. ju qu xu yu → ㄩ. 4. iu → ㄧㄡ, ui → ㄨㄟ, un → ㄨㄣ. 5. ong → ㄨㄥ, iong → ㄩㄥ. "
            "6. bo po mo fo → ㄛ; duo tuo guo → ㄨㄛ. 7. ie üe → ㄝ. 8. ian → ㄧㄢ, üan → ㄩㄢ."},
        {"h": "Taiwan readings", "body":
            "Typing in zhuyin means typing the TAIWAN reading. 垃圾 is ㄌㄜˋ ㄙㄜˋ, 星期 is ㄒㄧㄥ ㄑㄧˊ, 和 (and) is often ㄏㄢˋ, "
            "企業 is ㄑㄧˋ ㄧㄝˋ, 危險 is ㄨㄟˊ ㄒㄧㄢˇ. The pronunciation deck in your daily lessons covers these."},
    ], ["traps", "spell", "type"], "Stop translating through pinyin"),
    _unit(15, "Reading ruby zhuyin", "讀注音", "", [
        {"h": "Where it sits", "body":
            "In children's books, 國語日報 and subtitles for kids, zhuyin runs vertically down the right side of each character, "
            "with the tone mark at the upper right and the neutral dot on top. Switch any text in this app to 注音 to read it that way."},
        {"h": "注音文", "body":
            "Online, single symbols stand in for whole words: ㄅ = 吧, ㄇ = 嗎, ㄉ = 的, ㄋ = 呢, ㄏㄏ = 呵呵 (haha), ㄎㄎ = 科科 (hehe), "
            "ㄅㄅ = 掰掰. It reads as cute or lazy depending on who is judging."},
    ], ["read", "type"], "Read annotated text fluently"),
    _unit(16, "Homophones and choosing characters", "選字", "", [
        {"h": "How the input method thinks", "body":
            "After each tone key the input method guesses characters from context. Type whole words and phrases, not single "
            "characters, and it will almost always pick correctly: ㄒㄧㄢˋ ㄗㄞˋ gives 現在 at once, while ㄗㄞˋ alone could be 在 or 再."},
        {"h": "Fixing a wrong guess", "body":
            "Press ↓ to open the candidate list, pick with the number keys, and keep going. Enter commits the line. "
            "This is exactly how Microsoft 注音 (Windows) and 注音 on macOS behave, and how the built-in keyboard in this app behaves."},
        {"h": "Traditional traps", "body":
            "Because you type by sound, Simplified one-to-many characters matter: 頭髮 not 頭發, 乾淨 not 幹淨, 以後 not 以后, "
            "一隻狗 not 一只狗, 麵包 not 面包. Typing whole words lets the input method choose for you — but you must spot a wrong pick."},
    ], ["type", "homophones"], "Pick the right character"),
    _unit(17, "Set up your devices", "安裝注音輸入法", "", [
        {"h": "Windows", "body":
            "Settings → Time & language → Language & region → Add a language → 中文 (繁體, 台灣). It installs 微軟注音 (Microsoft Bopomofo). "
            "Switch with Win+Space; Shift toggles 中/英. In its options keep the layout on 標準 (Standard), which is 大千."},
        {"h": "macOS", "body":
            "System Settings → Keyboard → Input Sources → + → Chinese, Traditional → 注音 (Zhuyin). Layout: 標準. Switch with Ctrl+Space or the Globe key."},
        {"h": "iPhone and Android", "body":
            "iOS: Settings → General → Keyboard → Keyboards → Add → Chinese, Traditional → 注音. "
            "Android (Gboard): Languages → Add keyboard → 中文（繁體）→ 注音. The phone layout is the chart in rows, so the chart order you learned is the layout."},
        {"h": "Punctuation on the PC", "body":
            "In 微軟注音: Ctrl+, gives ，  Ctrl+. gives 。  Shift+/ gives ？  Shift+1 gives ！  Ctrl+' gives 、 and Ctrl+[ ] give 「」. "
            "The built-in keyboard here uses the same Shift combinations and also accepts Ctrl+, and Ctrl+."},
    ], ["type"], "Zhuyin installed everywhere you type"),
    _unit(18, "Typing words", "打詞", "", [
        {"h": "Rhythm", "body":
            "Symbols, tone, symbols, tone. Keep your eyes on the text, not the keys: you know the columns. "
            "Left hand does the initial, right hand the vowel, then a tone with whichever finger is free."},
        {"h": "Accuracy first", "body": "Speed comes from never backspacing. Aim for 95% before you push for speed."},
    ], ["type"], "Type common words smoothly"),
    _unit(19, "Punctuation and mixed text", "標點符號", "", [
        {"h": "Full-width marks", "body":
            "Chinese punctuation is full width: ， 。 ？ ！ ： ； 、 and Taiwan's quotation marks 「」 (inner quotes 『』). "
            "The enumeration comma 、 separates list items: 蘋果、香蕉、芭樂."},
        {"h": "English inside Chinese", "body": "Tap Shift to flip to English for LINE, App, OK, then Shift again. Taiwanese mix English words in freely."},
    ], ["type"], "Punctuate like a native"),
    _unit(20, "Speed building: phrases", "速度練習一", "", [
        {"h": "Chunks", "body": "Type in phrases of 3-6 characters and let conversion do the work. Do not stop to check after every character."},
    ], ["type"], "12+ characters a minute"),
    _unit(21, "Speed building: sentences", "速度練習二", "", [
        {"h": "Whole sentences", "body": "Type the whole clause, glance once, fix with ↓ only if a character is wrong, then commit with Enter."},
    ], ["type"], "18+ characters a minute"),
    _unit(22, "Typing checkpoint", "打字檢測", "", [
        {"h": "Two minutes", "body":
            "A timed passage. The year's targets: 15 字/分 by the end of month 1, 30 by month 4, 45 by month 8 and 60 by the end — "
            "about the speed of an ordinary Taiwanese office worker."},
    ], ["test"], "15 字/分 at 95% accuracy"),
]


def symbols_through(n: int) -> str:
    return "".join("".join(u["new"]) for u in UNITS[:n])


@lru_cache(maxsize=1)
def _word_bank() -> list[dict]:
    """HSK 1-5 words in Traditional with zhuyin, most common first."""
    from . import g2p

    out = []
    hs = decks.hsk_words()
    g2p.readings_many([w["trad"] for lv in range(1, 6) for w in hs[lv]])  # one batched pass, then cached
    for lv in range(1, 6):
        for w in hs[lv]:
            t = w["trad"]
            if not (1 <= len(t) <= 4) or not all(decks.HAN.match(c) for c in t):
                continue
            d = decks.describe(t)
            zy = d.get("zhuyin", "")
            if len(zy.split()) != len(t):
                continue
            out.append({"text": t, "zhuyin": zy, "pinyin": d.get("pinyin", ""), "en": w["en"], "lv": lv,
                        "simp": w["simp"], "syms": set(re.sub(r"[ ˊˇˋ˙]", "", zy))})
    return out


def _bank(allowed: str, must: str = "", maxlen: int = 4, minlen: int = 1) -> list[dict]:
    a = set(allowed)
    m = set(must)
    return [w for w in _word_bank() if w["syms"] <= a and (not m or w["syms"] & m) and minlen <= len(w["text"]) <= maxlen]


def _item(w: dict) -> dict:
    from . import text

    syls = w["zhuyin"].split()
    return {"text": w["text"], "zhuyin": w["zhuyin"], "pinyin": w["pinyin"], "en": w["en"],
            "keys": [zhuyin_to_keys(s) for s in syls], "tokens": text.annotate(w["text"], with_gloss=False)}


def unit_payload(n: int, seed: int | None = None) -> dict | None:
    if not 1 <= n <= len(UNITS):
        return None
    u = UNITS[n - 1]
    rng = random.Random(seed if seed is not None else n * 7919)
    known = symbols_through(n) or symbols_through(len(UNITS))
    new = "".join(u["new"])
    all_syms = INITIALS + MEDIALS + FINALS
    out = {k: u[k] for k in ("n", "title", "title_zh", "sections", "goal")}
    out["total"] = len(UNITS)
    out["symbols"] = [SYMBOLS[s] for s in new]
    out["known"] = [SYMBOLS[s] for s in known]
    out["keyboard"] = {"rows": KEYBOARD_ROWS, "map": KEY_TO_ZHUYIN}
    if n in (11, 12):
        want = "ㄧ" if n == 11 else "ㄨㄩ"
        out["compounds"] = compounds(want)
    drills = []
    for kind in u["drills"]:
        if kind == "match":
            pool = list(new) + rng.sample(list(known), min(len(known), 6))
            items = []
            for s in dict.fromkeys(pool):
                opts = {SYMBOLS[s]["pinyin"]}
                while len(opts) < 4:
                    opts.add(SYMBOLS[rng.choice(all_syms)]["pinyin"])
                o = sorted(opts)
                rng.shuffle(o)
                items.append({"prompt": s, "options": o, "answer": o.index(SYMBOLS[s]["pinyin"]), "symbol": s})
            rev = []
            for s in new:
                opts = {s}
                while len(opts) < 4:
                    opts.add(rng.choice(known if len(known) >= 4 else all_syms))
                o = sorted(opts)
                rng.shuffle(o)
                rev.append({"prompt": SYMBOLS[s]["pinyin"], "options": o, "answer": o.index(s), "symbol": s})
            drills.append({"type": "mcq", "title": "Symbol → sound", "items": items})
            drills.append({"type": "mcq", "title": "Sound → symbol", "items": rev})
        elif kind == "keys":
            seq = list(new) * 3 + rng.sample(list(known), min(len(known), 8))
            rng.shuffle(seq)
            drills.append({"type": "keys", "title": "Find the key", "items": [{"symbol": s, "key": ZHUYIN_TO_KEY[s]} for s in seq]})
        elif kind == "compound":
            comp = out.get("compounds", [])
            items = []
            for c in comp:
                opts = {c["pinyin"]}
                while len(opts) < 4:
                    opts.add(rng.choice(COMPOUNDS)[1])
                o = sorted(opts)
                rng.shuffle(o)
                items.append({"prompt": c["zy"], "options": o, "answer": o.index(c["pinyin"]), "say": c["sound"]})
            drills.append({"type": "mcq", "title": "Compound finals", "items": items})
        elif kind == "tones":
            items = []
            for w in rng.sample(_bank(all_syms, maxlen=1), 10):
                zy = w["zhuyin"]
                tone = "˙ neutral" if zy.startswith("˙") else {"ˊ": "ˊ 2nd", "ˇ": "ˇ 3rd", "ˋ": "ˋ 4th"}.get(zy[-1], "1st (no mark)")
                o = ["1st (no mark)", "ˊ 2nd", "ˇ 3rd", "ˋ 4th", "˙ neutral"]
                items.append({"prompt": f"{w['text']}  {w['pinyin']}", "options": o, "answer": o.index(tone), "say": w["text"]})
            drills.append({"type": "mcq", "title": "Which tone mark?", "items": items})
            keys = [{"symbol": s, "key": k} for s, k in (("ˊ", "6"), ("ˇ", "3"), ("ˋ", "4"), ("˙", "7"), ("ˉ", " "))] * 3
            rng.shuffle(keys)
            drills.append({"type": "keys", "title": "Tone keys", "items": keys})
        elif kind == "traps":
            traps = [("九", "ㄐㄧㄡˇ", ["ㄐㄧㄨˇ", "ㄐㄡˇ", "ㄓㄧㄡˇ"]), ("對", "ㄉㄨㄟˋ", ["ㄉㄨㄧˋ", "ㄉㄟˋ", "ㄊㄨㄟˋ"]),
                     ("春", "ㄔㄨㄣ", ["ㄔㄨㄥ", "ㄔㄩㄣ", "ㄑㄨㄣ"]), ("東", "ㄉㄨㄥ", ["ㄉㄛㄥ", "ㄉㄥ", "ㄉㄨㄣ"]),
                     ("用", "ㄩㄥˋ", ["ㄧㄨㄥˋ", "ㄧㄛㄥˋ", "ㄩㄣˋ"]), ("去", "ㄑㄩˋ", ["ㄑㄨˋ", "ㄐㄩˋ", "ㄑㄧㄩˋ"]),
                     ("是", "ㄕˋ", ["ㄕㄧˋ", "ㄙˋ", "ㄒㄧˋ"]), ("波", "ㄅㄛ", ["ㄅㄨㄛ", "ㄅㄜ", "ㄆㄛ"]),
                     ("多", "ㄉㄨㄛ", ["ㄉㄛ", "ㄉㄡ", "ㄊㄨㄛ"]), ("謝", "ㄒㄧㄝˋ", ["ㄒㄧㄜˋ", "ㄒㄝˋ", "ㄕㄧㄝˋ"]),
                     ("學", "ㄒㄩㄝˊ", ["ㄒㄨㄝˊ", "ㄒㄩㄜˊ", "ㄕㄩㄝˊ"]), ("遠", "ㄩㄢˇ", ["ㄧㄨㄢˇ", "ㄨㄢˇ", "ㄩㄤˇ"]),
                     ("我", "ㄨㄛˇ", ["ㄨㄜˇ", "ㄛˇ", "ㄨㄡˇ"]), ("也", "ㄧㄝˇ", ["ㄧㄜˇ", "ㄝˇ", "ㄧㄟˇ"]),
                     ("天", "ㄊㄧㄢ", ["ㄊㄧㄝㄣ", "ㄊㄧㄤ", "ㄊㄢ"]), ("窮", "ㄑㄩㄥˊ", ["ㄑㄧㄨㄥˊ", "ㄑㄧㄛㄥˊ", "ㄑㄩㄣˊ"])]
            items = []
            for ch, right, wrong in traps:
                o = [right] + wrong
                rng.shuffle(o)
                items.append({"prompt": f"{ch}  {decks.describe(ch).get('pinyin', '')}", "options": o, "answer": o.index(right), "say": ch})
            drills.append({"type": "mcq", "title": "Pinyin traps", "items": items})
        elif kind == "spell":
            # Full-tone syllables only: a particle such as 嗎 or 吧 has no clear tone when heard alone.
            pool = [w for w in _bank(known, must=new or known, maxlen=1) if "˙" not in w["zhuyin"]]
            if len(pool) < 6:
                pool = [w for w in _bank(known, maxlen=1) if "˙" not in w["zhuyin"]]
            pick = rng.sample(pool[:150], min(10, len(pool[:150])))
            drills.append({"type": "spell", "title": "Spell it in zhuyin", "items": [_item(w) for w in pick]})
        elif kind == "read":
            pool = _bank(all_syms, minlen=2, maxlen=4)
            pick = rng.sample(pool[:900], 12)
            items = []
            for w in pick:
                others = rng.sample(pool[:900], 3)
                o = [w["text"]] + [x["text"] for x in others if x["text"] != w["text"]]
                rng.shuffle(o)
                items.append({"prompt": w["zhuyin"], "options": o, "answer": o.index(w["text"]), "say": w["text"]})
            drills.append({"type": "mcq", "title": "Read the zhuyin", "items": items})
        elif kind == "homophones":
            pairs = [("頭ㄈㄚˇ", ["髮", "發"], 0, "頭髮 hair"), ("ㄈㄚ現", ["發", "髮"], 0, "發現 discover"),
                     ("以ㄏㄡˋ", ["後", "后"], 0, "以後 afterwards"), ("ㄍㄢ淨", ["乾", "幹", "干"], 0, "乾淨 clean"),
                     ("ㄍㄢˋ嘛", ["幹", "乾", "干"], 0, "幹嘛 what for"), ("一ㄓ狗", ["隻", "只"], 0, "一隻狗 one dog"),
                     ("ㄓˇ有", ["只", "隻"], 0, "只有 only"), ("ㄇㄧㄢˋ包", ["麵", "面"], 0, "麵包 bread"),
                     ("見ㄇㄧㄢˋ", ["面", "麵"], 0, "見面 meet"), ("ㄌㄧˇ面", ["裡", "里"], 0, "裡面 inside"),
                     ("公ㄌㄧˇ", ["里", "裡"], 0, "公里 kilometre"), ("ㄗㄞˋ見", ["再", "在"], 0, "再見 goodbye"),
                     ("現ㄗㄞˋ", ["在", "再"], 0, "現在 now"), ("ㄩㄣˊ彩", ["雲", "云"], 0, "雲彩 clouds"),
                     ("ㄊㄞˊ灣", ["台", "抬", "颱"], 0, "台灣"), ("ㄊㄞˊ風", ["颱", "台", "抬"], 0, "颱風 typhoon")]
            items = []
            for prompt, opts, ans, gloss in pairs:
                o = list(opts)
                right = o[ans]
                rng.shuffle(o)
                items.append({"prompt": f"{prompt}   ({gloss})", "options": o, "answer": o.index(right)})
            drills.append({"type": "mcq", "title": "Which character?", "items": items})
        elif kind in ("type", "test"):
            if n <= 10:
                pool = _bank(known, must=new, minlen=1, maxlen=2) or _bank(known, maxlen=2)
                pick = rng.sample(pool[:200], min(10, len(pool[:200])))
                drills.append({"type": "type", "title": "Type the word", "items": [_item(w) for w in pick]})
            elif n <= 18:
                pool = _bank(all_syms, minlen=2, maxlen=3)
                lo = (n - 11) * 60
                pick = rng.sample(pool[lo:lo + 260], 12)
                drills.append({"type": "type", "title": "Type the word", "items": [_item(w) for w in pick]})
            else:
                sents = typing_sentences(6 if kind == "type" else 8, rng)
                drills.append({"type": "type", "title": "Type the sentence" if kind == "type" else "Timed test",
                               "timed": kind == "test", "items": sents})
    out["drills"] = drills
    return out


BASE_SENTENCES = [
    ("我今天早上喝了一杯豆漿。", "I had a cup of soy milk this morning."),
    ("你要不要一起去吃晚餐？", "Do you want to go get dinner together?"),
    ("這個週末我們去夜市逛逛吧。", "Let's go wander the night market this weekend."),
    ("請問捷運站怎麼走？", "Excuse me, how do I get to the MRT station?"),
    ("我想要一杯半糖少冰的紅茶。", "I'd like a black tea, half sugar, less ice."),
    ("外面在下雨，記得帶傘。", "It's raining outside, remember your umbrella."),
    ("不好意思，可以借過一下嗎？", "Excuse me, could I get past?"),
    ("我正在學怎麼用注音打字。", "I'm learning how to type with zhuyin."),
    ("他每天騎機車去公司上班。", "He rides a scooter to work every day."),
    ("這家店的牛肉麵真的很好吃。", "This shop's beef noodles are really good."),
    ("明天要不要去看那部電影？", "Want to go see that movie tomorrow?"),
    ("我的手機快沒電了，可以借我充電嗎？", "My phone's about to die, can I borrow a charger?"),
    ("颱風要來了，大家記得關好門窗。", "A typhoon is coming, everyone remember to shut doors and windows."),
    ("我覺得台灣的便利商店非常方便。", "I think convenience stores in Taiwan are really convenient."),
    ("你週末通常都在做什麼？", "What do you usually do on weekends?"),
    ("麻煩給我一份蛋餅和一杯冰奶茶。", "One egg crepe and an iced milk tea, please."),
    ("我們約晚上七點在車站見面。", "Let's meet at the station at seven tonight."),
    ("最近工作比較忙，常常要加班。", "Work's been busy lately, I often have to work late."),
    ("雖然很累，但是我還是想去運動。", "I'm tired, but I still want to go exercise."),
    ("謝謝你幫我這麼多忙，改天請你吃飯。", "Thanks for all the help, I'll treat you to a meal sometime."),
]


def typing_sentences(n: int, rng: random.Random | None = None) -> list[dict]:
    """Sentences for typing practice: seen material first (reviewed vocabulary examples), then stock sentences."""
    rng = rng or random.Random()
    pool = [{"zh": zh, "en": en} for zh, en in BASE_SENTENCES]
    rows = db.q("SELECT data FROM cards WHERE kind='word' AND reps>0 ORDER BY last_review DESC LIMIT 150")
    import json

    for r in rows:
        ex = (json.loads(r["data"]) or {}).get("example")
        if ex and ex.get("zh") and 6 <= len(ex["zh"]) <= 26:
            pool.append({"zh": ex["zh"], "en": ex.get("en", "")})
    pick = rng.sample(pool, min(n, len(pool)))
    return [sentence_item(p["zh"], p.get("en", "")) for p in pick]


def sentence_item(zh: str, en: str = "") -> dict:
    from . import text

    toks = text.annotate(zh, with_gloss=False)
    syls, keys = [], []
    for t in toks:
        if t["han"]:
            for c in t["chars"]:
                zy = c.get("cz") or c["zy"]
                syls.append(zy)
                keys.append(zhuyin_to_keys(zy) if zy else "")
    return {"text": zh, "en": en, "zhuyin": " ".join(syls), "keys": keys, "tokens": toks}


def overview() -> dict:
    done = set(db.get_setting("zhuyin_done", []) or [])
    return {
        "units": [{"n": u["n"], "title": u["title"], "title_zh": u["title_zh"], "goal": u["goal"],
                   "new": u["new"], "done": u["n"] in done} for u in UNITS],
        "symbols": {"initials": [SYMBOLS[s] for s in INITIALS], "medials": [SYMBOLS[s] for s in MEDIALS],
                    "finals": [SYMBOLS[s] for s in FINALS]},
        "compounds": compounds(),
        "tones": [{"mark": "", "name": "1st", "key": "Space", "ex": "媽 ㄇㄚ"}, {"mark": "ˊ", "name": "2nd", "key": "6", "ex": "麻 ㄇㄚˊ"},
                  {"mark": "ˇ", "name": "3rd", "key": "3", "ex": "馬 ㄇㄚˇ"}, {"mark": "ˋ", "name": "4th", "key": "4", "ex": "罵 ㄇㄚˋ"},
                  {"mark": "˙", "name": "neutral", "key": "7", "ex": "嗎 ˙ㄇㄚ"}],
        "keyboard": {"rows": KEYBOARD_ROWS, "map": KEY_TO_ZHUYIN},
        "done": sorted(done),
    }


def mark_done(n: int) -> None:
    done = db.get_setting("zhuyin_done", []) or []
    if n not in done:
        done.append(n)
        db.set_setting("zhuyin_done", done)


def progress() -> dict:
    """What the learner can read and type so far. The rest of the app leans on this: pinyin stays
    next to syllables whose symbols have not been taught, and typing tasks wait for the keyboard."""
    from . import curriculum

    done = set(db.get_setting("zhuyin_done", []) or [])
    known = "".join(s for u in UNITS if u["n"] in done for s in u["new"])
    through = 0
    for u in UNITS:
        if u["n"] not in done:
            break
        through = u["n"]
    return {"known": known, "all_symbols": len(set(known)) >= len(INITIALS + MEDIALS + FINALS), "through": through,
            "next": next_unit(), "total": len(UNITS), "can_type": through >= curriculum.TYPING_FROM_UNIT,
            "can_write": through >= curriculum.WRITING_FROM_UNIT, "typing_from": curriculum.TYPING_FROM_UNIT,
            "writing_from": curriculum.WRITING_FROM_UNIT}


def next_unit() -> int | None:
    done = set(db.get_setting("zhuyin_done", []) or [])
    for u in UNITS:
        if u["n"] not in done:
            return u["n"]
    return None
