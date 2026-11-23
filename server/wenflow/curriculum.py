"""The 52-week plan (content/curriculum.json) and the shape of each day's 30-minute lesson."""
from __future__ import annotations

from . import content_store

PHASES = {
    0: {"name": "Foundations", "zh": "注音與繁體入門", "weeks": "1–4",
        "about": "All 37 zhuyin symbols, the 大千 keyboard, and your first few hundred Traditional characters."},
    1: {"name": "Daily Life", "zh": "台灣日常", "weeks": "5–16",
        "about": "Everyday Taiwan: food, transport, errands. Traditional reading becomes automatic; typing reaches 30 字/分."},
    2: {"name": "Taiwan Flavour", "zh": "台灣味", "weeks": "17–32",
        "about": "School life, slang, media and relationships — the world of 那些年. HSK 6 vocabulary begins in earnest."},
    3: {"name": "Advanced", "zh": "進階與書面語", "weeks": "33–48",
        "about": "Professional and literary Mandarin: news, argument, narration. You finish the novel."},
    4: {"name": "Mastery", "zh": "總驗收", "weeks": "49–52", "about": "Consolidation and final checkpoints."},
}

# (block type, minutes). The zhuyin block leads the day: everything after it may rely on what it has
# just taught, and on nothing more (see fit_to_zhuyin). Phase 0 is zhuyin-heavy; later phases rotate
# through seven day shapes that open with a keyboard warm-up.
PHASE0_DAYS = [
    [("zhuyin", 9), ("review", 4), ("chars", 6), ("vocab", 4), ("reading", 4), ("shadow", 3)],
    [("zhuyin", 9), ("review", 4), ("chars", 6), ("vocab", 4), ("dictation", 3), ("shadow", 4)],
    [("zhuyin", 9), ("review", 4), ("chars", 6), ("vocab", 4), ("reading", 4), ("writing", 3)],
    [("zhuyin", 9), ("review", 4), ("chars", 6), ("vocab", 4), ("pron", 3), ("shadow", 4)],
    [("zhuyin", 9), ("review", 4), ("chars", 6), ("vocab", 4), ("reading", 4), ("shadow", 3)],
    [("zhuyin", 8), ("review", 4), ("vocab", 4), ("video", 8), ("conversation", 6)],
    [("zhuyin", 8), ("review", 5), ("checkpoint", 6), ("conversation", 7), ("writing", 4)],
]

LATER_DAYS = [
    [("typing", 4), ("review", 5), ("chars", 5), ("vocab", 5), ("reading", 7), ("shadow", 4)],
    [("dictation", 4), ("review", 5), ("vocab", 5), ("grammar", 5), ("video", 8), ("writing", 3)],
    [("typing", 3), ("review", 5), ("chars", 5), ("vocab", 4), ("book", 9), ("shadow", 4)],
    [("review", 5), ("pron", 3), ("vocab", 5), ("grammar", 4), ("conversation", 10), ("writing", 3)],
    [("dictation", 4), ("review", 5), ("chars", 5), ("vocab", 4), ("news", 8), ("shadow", 4)],
    [("review", 5), ("vocab", 4), ("video", 12), ("conversation", 9)],
    [("review", 6), ("checkpoint", 7), ("book", 11), ("writing", 6)],
]

# Blocks that open a day with the zhuyin keyboard.
LEAD_BLOCKS = ("zhuyin", "typing", "dictation")

# What the zhuyin course has to have covered before a block may ask for it. Units 1-10 teach the 37
# symbols, 11-12 the compound finals, 13 the tone keys, 16 how to choose between characters.
TYPING_FROM_UNIT = 13    # typing out a given sentence (dictation)
WRITING_FROM_UNIT = 16   # composing your own text


def fit_to_zhuyin(tpl: list[tuple[str, int]], level: int | None) -> list[tuple[str, int]]:
    """Keep a day within the zhuyin the learner has by the time its first block is done.

    `level` is the last zhuyin unit covered once today's zhuyin block is finished (None when the
    course is complete). A block that needs more than that is swapped for one that does not, in the
    same slot and for the same number of minutes.
    """
    if level is None:
        return tpl
    have = {t for t, _ in tpl}
    out = []
    for t, m in tpl:
        if (t == "dictation" and level < TYPING_FROM_UNIT) or (t == "writing" and level < WRITING_FROM_UNIT):
            t = next((alt for alt in ("reading", "shadow", "pron") if alt not in have), "shadow")
            have.add(t)
        out.append((t, m))
    return out


# New vocabulary per day by phase: (taiwan, hsk6, book)
VOCAB_MIX = {0: (5, 0, 0), 1: (4, 3, 2), 2: (3, 5, 2), 3: (2, 6, 2), 4: (1, 6, 2)}

# Reading passage length (characters) and book chunk size by phase.
READING_LEN = {0: (90, 140), 1: (240, 340), 2: (340, 460), 3: (460, 620), 4: (520, 680)}
BOOK_CHUNK = {0: 400, 1: 700, 2: 1100, 3: 1500, 4: 1700}

BLOCK_TITLES = {
    "review": ("Review", "複習"), "zhuyin": ("Zhuyin", "注音"), "typing": ("Typing", "打字"),
    "dictation": ("Dictation", "聽寫"), "chars": ("Traditional characters", "繁體字"), "vocab": ("New words", "生詞"),
    "grammar": ("Grammar", "語法"), "pron": ("Taiwan pronunciation", "台灣讀音"), "reading": ("Reading", "閱讀"),
    "news": ("News reading", "新聞"), "book": ("The novel", "那些年"), "video": ("Video", "影片"),
    "shadow": ("Shadowing", "跟讀"), "conversation": ("Conversation", "會話"), "writing": ("Writing", "寫作"),
    "checkpoint": ("Weekly checkpoint", "週測"),
}


def weeks() -> list[dict]:
    return (content_store.load_json("curriculum.json", {}) or {}).get("weeks", [])


def week(n: int) -> dict:
    ws = weeks()
    if not ws:
        return {"week": n, "phase": 0 if n <= 4 else 1 if n <= 16 else 2 if n <= 32 else 3 if n <= 48 else 4,
                "title": f"Week {n}", "title_zh": f"第{n}週", "theme": "", "goals": [], "scenario_ids": [],
                "vocab_domains": [], "grammar_level": 4, "reading_genre": "short essay", "writing_task": "",
                "speaking_focus": "", "book_target": "0%", "milestone": None}
    return ws[min(max(n, 1), len(ws)) - 1]


def position(day: int) -> dict:
    """Where lesson number `day` (1-based) sits in the year."""
    day = max(1, day)
    w = min((day - 1) // 7 + 1, 52)
    dow = (day - 1) % 7
    info = week(w)
    return {"day": day, "week": w, "dow": dow, "phase": info.get("phase", 0), "info": info}


def template(day: int) -> list[tuple[str, int]]:
    pos = position(day)
    return list((PHASE0_DAYS if pos["phase"] == 0 else LATER_DAYS)[pos["dow"]])


def overview() -> list[dict]:
    out = []
    for w in weeks():
        out.append({k: w.get(k) for k in ("week", "phase", "title", "title_zh", "theme", "goals", "scenario_ids",
                                           "book_target", "milestone", "zhuyin_focus", "traditional_focus",
                                           "speaking_focus", "writing_task", "reading_genre")})
    return out
