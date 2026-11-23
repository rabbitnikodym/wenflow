"""CC-CEDICT dictionary with Taiwan pronunciations, HSK levels, frequency and a zhuyin IME index.

Built once by `build()` into data/dict.sqlite from files downloaded to data/raw/.
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import threading
import zipfile

import httpx

from .config import DICT_DB, RAW_DIR
from .zhuyin import pinyin_num_to_marks, pinyin_to_zhuyin, zhuyin_key

CEDICT_URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip"
HSK_URL = "https://raw.githubusercontent.com/drkameleon/complete-hsk-vocabulary/main/complete.json"

LINE_RE = re.compile(r"^(\S+) (\S+) \[([^\]]+)\] /(.*)/$")
# Only a stand-alone note applies to the whole entry; "(Taiwan pr. [x])" inside a sense is sense-specific.
TW_PR_RE = re.compile(r"^Taiwan pr\. \[([^\]]+)\]$")
ALT_TW_RE = re.compile(r"Taiwan pr\. \[([^\]]+)\]")


def _download(url: str, dest) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    print(f"downloading {url}")
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)


def _norm_py(py: str) -> str:
    return " ".join(s.lower().replace("u:", "ü") for s in py.split())


def _split_run(py: str, n: int) -> str:
    """'xia4hai2' -> 'xia4 hai2' (CEDICT sometimes writes Taiwan readings without spaces)."""
    if len(py.split()) == n:
        return py
    parts = re.findall(r"[a-zü:]+[1-5]", py.replace(" ", ""))
    return " ".join(parts) if len(parts) == n else py


def build(force: bool = False) -> None:
    if DICT_DB.exists() and not force:
        return
    cedict_zip = RAW_DIR / "cedict.zip"
    hsk_json = RAW_DIR / "hsk_complete.json"
    _download(CEDICT_URL, cedict_zip)
    _download(HSK_URL, hsk_json)

    import jieba  # frequency table (counts from a large simplified corpus)
    import opencc

    jieba.initialize()
    freq = jieba.dt.FREQ

    # Traditional word and character frequencies: convert the corpus vocabulary with OpenCC's
    # phrase-aware Taiwan conversion (头发 -> 頭髮, 发现 -> 發現) and sum the counts. This is what lets the
    # input method rank 發 above 髮 and 裡 above 里 even though each pair shares one Simplified character.
    cc = opencc.OpenCC("s2tw")
    items = [(w, f) for w, f in freq.items() if f > 0 and "\n" not in w]
    tw_word: dict[str, int] = {}
    tw_char: dict[str, int] = {}
    trad_of: dict[str, str] = {}
    for i in range(0, len(items), 5000):
        chunk = items[i:i + 5000]
        conv = cc.convert("\n".join(w for w, _ in chunk)).replace("臺", "台").split("\n")
        if len(conv) != len(chunk):
            conv = [cc.convert(w).replace("臺", "台") for w, _ in chunk]
        for (w, f), t in zip(chunk, conv):
            tw_word[t] = tw_word.get(t, 0) + f
            for ch in t:
                tw_char[ch] = tw_char.get(ch, 0) + f
            trad_of[w] = t

    # How often each character takes each reading (背 bèi vs bēi, 地 dì vs de), from phrase readings.
    from pypinyin import Style, lazy_pinyin

    read_cnt: dict[tuple[str, str], int] = {}
    read_tot: dict[str, int] = {}
    phrases: list[tuple[str, list[str], int]] = []
    for w, f in items:
        t = trad_of.get(w, w)
        if len(t) != len(w) or len(w) > 6:
            continue
        pys = lazy_pinyin(w, style=Style.TONE3, neutral_tone_with_five=True, errors="ignore")
        if len(pys) != len(w):
            continue
        pys = [x.replace("v", "ü") for x in pys]
        for ch, x in zip(t, pys):
            read_cnt[(ch, x)] = read_cnt.get((ch, x), 0) + f
            read_tot[ch] = read_tot.get(ch, 0) + f
        if 2 <= len(w) <= 5 and f >= 12:
            phrases.append((t, pys, f))

    hsk: dict[str, int] = {}
    for item in json.load(open(hsk_json, encoding="utf-8")):
        lv = [int(l.split("-")[1]) for l in item.get("level", []) if l.startswith("old-")]
        if lv:
            hsk[item["simplified"]] = min(lv)

    tw_overrides = _load_pron_overrides()

    tmp = DICT_DB.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.executescript(
        """
        CREATE TABLE entries(
          id INTEGER PRIMARY KEY, trad TEXT, simp TEXT, pinyin TEXT, tw_pinyin TEXT,
          defs TEXT, freq INTEGER, hsk INTEGER, proper INTEGER);
        CREATE TABLE ime(key TEXT, toneless TEXT, word TEXT, freq INTEGER, len INTEGER, cfreq INTEGER);
        """
    )
    with zipfile.ZipFile(cedict_zip) as z:
        name = [n for n in z.namelist() if n.endswith(".u8")][0]
        lines = io.TextIOWrapper(z.open(name), encoding="utf-8").read().splitlines()
        # Traditional variants that share one Simplified character (發/髮 <- 发) split its count.
        variants: dict[str, set[str]] = {}
        variants_all: set[str] = set()
        for line in lines:
            m = LINE_RE.match(line.strip())
            if m and len(m.group(1)) == 1:
                variants.setdefault(m.group(2), set()).add(m.group(1))
                variants_all.add(m.group(1))
        rows = []
        ime_rows = []
        seen_ime: set[tuple[str, str]] = set()
        for line in lines:
            if line.startswith("#"):
                continue
            m = LINE_RE.match(line.strip())
            if not m:
                continue
            trad, simp, py, defs_raw = m.groups()
            defs = [d for d in defs_raw.split("/") if d]
            proper = py[:1].isupper()
            py = _norm_py(py)
            tw = None
            for d in defs:
                mm = TW_PR_RE.match(d.strip())
                if mm:
                    tw = _split_run(_norm_py(mm.group(1)), len(trad))
            if trad in tw_overrides and not proper:
                o_tw, o_tl, o_cn = tw_overrides[trad]
                if _toneless_num(py) in (o_tl, o_cn):  # same sense as the curated reading
                    tw = o_tw
            if tw and len(tw.split()) != len(py.split()):
                tw = None
            f = freq.get(simp, 0) or 0
            rows.append((trad, simp, py, tw, json.dumps(defs, ensure_ascii=False), f, hsk.get(simp), int(proper)))
            # Input-method rank. Single characters: stand-alone count, shared between Traditional variants
            # and between readings. Words: Traditional word count.
            variant_only = all(d.startswith(("variant of", "old variant", "used in", "Japanese variant", "surname",
                                             "archaic variant")) for d in defs) and "台" not in trad
            if len(trad) == 1:
                vs = variants.get(simp, {trad})
                tot = sum(tw_char.get(v, 0) for v in vs) or 1
                base_f = (freq.get(simp, 0) or 0) * (tw_char.get(trad, 0) / tot if len(vs) > 1 else 1.0)
                rt = read_tot.get(trad, 0)
                share = (read_cnt.get((trad, py), 0) + 0.01 * rt + 1) / (1.01 * rt + 1) if rt else 1.0
                f_ime = int(base_f * share)
                c_ime = int(tw_char.get(trad, 0) * share)
            else:
                f_ime = tw_word.get(trad, 0) if trad in tw_word else (0 if "臺" in trad else min(f, 40))
                f_ime = max(f_ime, 2)
                c_ime = f_ime
            if variant_only:
                f_ime, c_ime = f_ime // 1000, c_ime // 1000
            for p in {tw or py, py}:
                syls = p.split()
                if len(syls) != len(trad):
                    continue
                zys = [pinyin_to_zhuyin(s) for s in syls]
                key = zhuyin_key(zys)
                toneless = re.sub(r"[ˉˊˇˋ˙]", "", key)
                ime_rows.append((key, toneless, trad, f_ime, len(trad), c_ime))
                seen_ime.add((key, trad))
        # Alternate Taiwan readings must be typeable too: sense-specific ones the dictionary mentions in
        # passing (和 hàn) and every reading the annotation model can produce for a character.
        alt_rows = []
        for trad, simp, py, tw, defs_json, f, _h, _p in rows:
            for mm in ALT_TW_RE.finditer(defs_json):
                alt = _split_run(_norm_py(mm.group(1).split(",")[0]), len(trad))
                syls = alt.split()
                if len(syls) != len(trad):
                    continue
                key = zhuyin_key([pinyin_to_zhuyin(x) for x in syls])
                if (key, trad) not in seen_ime and re.search(r"[ㄅ-ㄩ]", key):
                    seen_ime.add((key, trad))
                    base = (freq.get(simp, 0) or 0) if len(trad) == 1 else tw_word.get(trad, 0)
                    alt_rows.append((key, re.sub(r"[ˉˊˇˋ˙]", "", key), trad, max(2, base // 8), len(trad), max(2, base // 8)))
        try:
            import g2pw

            with open(os.path.join(os.path.dirname(g2pw.__file__), "char_bopomofo_dict.json"), encoding="utf-8") as fh:
                model_readings = json.load(fh)
            tone_mark = {"1": "ˉ", "2": "ˊ", "3": "ˇ", "4": "ˋ", "5": "˙"}
            for ch in variants_all:
                for b in model_readings.get(ch, []):
                    key = b[:-1] + tone_mark.get(b[-1], "ˉ")
                    if (key, ch) not in seen_ime:
                        seen_ime.add((key, ch))
                        alt_rows.append((key, b[:-1], ch, 1, 1, 1))
        except Exception:  # noqa: BLE001 - the model package is optional
            pass
        ime_rows += alt_rows
        # Common phrases from the corpus that the dictionary does not list (一杯, 班上, 我要).
        for t, pys, f in phrases:
            zys = [pinyin_to_zhuyin(x) for x in pys]
            if any(not re.search(r"[ㄅ-ㄩ]", z) for z in zys):
                continue
            key = zhuyin_key(zys)
            if (key, t) in seen_ime:
                continue
            seen_ime.add((key, t))
            ime_rows.append((key, re.sub(r"[ˉˊˇˋ˙]", "", key), t, tw_word.get(t, f), len(t), tw_word.get(t, f)))
        # Curated Taiwan vocabulary must be typeable and rank well even where the corpus has never seen it.
        from .content_store import book_pack, taiwan_vocab

        names = [{"trad": c.get("name", ""), "pinyin": c.get("pinyin", "")} for c in book_pack().get("characters", [])]
        for item in list(taiwan_vocab()) + list(book_pack().get("vocab", [])) + names:
            w, syls = item.get("trad", ""), (item.get("pinyin") or "").split()
            if not (1 < len(w) <= 8) or len(syls) != len(w) or not all("\u3400" <= c <= "\u9fff" for c in w):
                continue
            zys = [pinyin_to_zhuyin(x) for x in syls]
            if any(not re.search(r"[ㄅ-ㄩ]", z) for z in zys):
                continue
            key = zhuyin_key(zys)
            fw = max(3000, tw_word.get(w, 0))
            ime_rows.append((key, re.sub(r"[ˉˊˇˋ˙]", "", key), w, fw, len(w), fw))
        db.executemany("INSERT INTO entries(trad,simp,pinyin,tw_pinyin,defs,freq,hsk,proper) VALUES(?,?,?,?,?,?,?,?)", rows)
        db.executemany("INSERT INTO ime VALUES(?,?,?,?,?,?)", ime_rows)
    db.executescript(
        """
        CREATE INDEX ix_trad ON entries(trad);
        CREATE INDEX ix_simp ON entries(simp);
        CREATE INDEX ix_ime ON ime(key);
        CREATE INDEX ix_ime_tl ON ime(toneless);
        """
    )
    db.commit()
    db.close()
    tmp.replace(DICT_DB)
    global _generation
    _generation += 1
    print(f"dictionary built: {len(rows)} entries")


def _load_pron_overrides() -> dict[str, tuple[str, list[str], list[str]]]:
    """Taiwan readings from the curated list: trad -> (numbered tw reading, toneless tw, toneless mainland).
    Only readings that are both the dictionary standard and what people say are applied."""
    from .content_store import load_json
    from .zhuyin import split_tone

    out: dict[str, tuple[str, list[str], list[str]]] = {}
    for item in load_json("pronunciation_diffs.json", []) or []:
        if item.get("status", "standard") != "standard" or item.get("group") == "erhua":
            continue
        trad = item.get("trad", "")
        syls = [split_tone(s) for s in item.get("tw", "").replace(",", " ").split()]
        # Single characters (和, 誰, 這) are left to the context model: a blanket override would be wrong.
        if len(trad) < 2 or len(syls) != len(trad):
            continue
        cn = [split_tone(s)[0] for s in (item.get("cn") or item.get("mainland") or "").replace(",", " ").split()]
        out[trad] = (" ".join(f"{b}{t}" for b, t in syls), [b for b, _ in syls], cn)
    return out


def _toneless_num(py: str) -> list[str]:
    return [re.sub(r"[1-5]$", "", s) for s in py.split()]


_local = threading.local()
_generation = 0  # bumped when the dictionary is rebuilt, so every thread reopens it


def _conn() -> sqlite3.Connection:
    """One read connection per thread: a connection shared between the warm-up thread and request
    threads fails under concurrent use ("bad parameter or other API misuse")."""
    c = getattr(_local, "conn", None)
    if c is None or getattr(_local, "generation", -1) != _generation:
        if not DICT_DB.exists():
            build()
        c = sqlite3.connect(DICT_DB, timeout=30)
        c.row_factory = sqlite3.Row
        _local.conn, _local.generation = c, _generation
    return c


def _fmt(row: sqlite3.Row) -> dict:
    py = row["tw_pinyin"] or row["pinyin"]
    syls = py.split()
    return {
        "trad": row["trad"],
        "simp": row["simp"],
        "pinyin": " ".join(pinyin_num_to_marks(s) for s in syls),
        "pinyin_num": py,
        "zhuyin": " ".join(pinyin_to_zhuyin(s) for s in syls),
        "mainland_pinyin": " ".join(pinyin_num_to_marks(s) for s in row["pinyin"].split()) if row["tw_pinyin"] else None,
        "defs": [d for d in json.loads(row["defs"]) if not d.startswith("Taiwan pr.")],
        "freq": row["freq"],
        "hsk": row["hsk"],
        "proper": bool(row["proper"]),
    }


def lookup(word: str) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM entries WHERE trad=? OR simp=? ORDER BY (trad=?) DESC, freq DESC", (word, word, word)
    ).fetchall()
    # Exact traditional matches first; proper-noun senses (surnames, place names) last.
    rows = sorted(rows, key=lambda r: (r["trad"] != word, r["proper"]))
    return [_fmt(r) for r in rows]


def has_word(word: str) -> bool:
    return _conn().execute("SELECT 1 FROM entries WHERE trad=? LIMIT 1", (word,)).fetchone() is not None


def best_pinyin(word: str) -> str | None:
    """Taiwan-preferred numbered pinyin for an exact traditional word, most common reading first."""
    r = _conn().execute(
        "SELECT pinyin, tw_pinyin FROM entries WHERE trad=? ORDER BY proper, freq DESC LIMIT 1",
        (word,),
    ).fetchone()
    if not r:
        return None
    return r["tw_pinyin"] or r["pinyin"]


def word_info(word: str) -> tuple[int, int | None]:
    """(frequency, hsk level) for difficulty estimates."""
    r = _conn().execute("SELECT max(freq) f, min(hsk) h FROM entries WHERE trad=? OR simp=?", (word, word)).fetchone()
    return (r["f"] or 0, r["h"]) if r else (0, None)


def ime_candidates(key: str, limit: int = 30) -> list[dict]:
    """Candidates for a zhuyin key (see zhuyin.zhuyin_key). A key with no tone marks matches toneless."""
    c = _conn()
    has_tone = any(ch in key for ch in "ˉˊˇˋ˙")
    col = "key" if has_tone else "toneless"
    rows = c.execute(
        f"SELECT word, max(freq) f FROM ime WHERE {col}=? GROUP BY word ORDER BY f DESC, word LIMIT ?", (key, limit)
    ).fetchall()
    return [{"word": r["word"], "freq": r["f"]} for r in rows]


def ime_prefix_words(first_key: str, limit: int = 20) -> list[dict]:
    """Multi-syllable words beginning with a syllable key, for the candidate bar."""
    rows = _conn().execute(
        "SELECT word, key, max(freq) f FROM ime WHERE key LIKE ? AND len>1 GROUP BY word ORDER BY f DESC LIMIT ?",
        (first_key + "%", limit),
    ).fetchall()
    return [{"word": r["word"], "key": r["key"], "freq": r["f"]} for r in rows]


def hsk_level(word_simp: str) -> int | None:
    r = _conn().execute("SELECT min(hsk) h FROM entries WHERE simp=? OR trad=?", (word_simp, word_simp)).fetchone()
    return r["h"] if r else None


def hsk_words(max_level: int) -> list[str]:
    rows = _conn().execute("SELECT DISTINCT trad FROM entries WHERE hsk IS NOT NULL AND hsk<=?", (max_level,)).fetchall()
    return [r["trad"] for r in rows]


IME_TOTAL = 60_000_000.0
IME_MAX_WORD = 6
IME_ALPHA = 0.7      # single characters: blend of stand-alone count and count inside words
IME_LEN_BONUS = 1.0  # per extra character, favours real words over runs of single characters


def ime_convert(keys: list[str], limit: int = 40, hint: str = "", expect: str = "") -> dict:
    """Convert a run of typed syllables to characters the way a smart 注音 input method does.

    keys: one canonical key per syllable ('ㄋㄧˇ', 'ㄊㄚˉ', 'ㄉㄜ˙'). Returns the most likely conversion
    (best path under a unigram word model) plus candidates for the start of the run, longest words first.
    `expect` is the exact text the user is known to be typing next, one character per syllable (a drill's
    remaining target): a candidate that matches it at the same position wins. `hint` is looser — any
    word that occurs in it is favoured. Both stand in for the sentence context a full input method uses.
    """
    import math

    keys = [k for k in keys if k]
    n = len(keys)
    if not n:
        return {"best": "", "segments": [], "candidates": []}
    c = _conn()
    span: dict[tuple[int, int], list[tuple[str, float]]] = {}
    for i in range(n):
        for j in range(i + 1, min(n, i + IME_MAX_WORD) + 1):
            rows = c.execute(
                "SELECT word, max(freq) f, max(cfreq) cf FROM ime WHERE key=? AND len=? GROUP BY word "
                "ORDER BY f DESC, word LIMIT ?", ("".join(keys[i:j]), j - i, max(limit, 60))).fetchall()
            if not rows:
                continue
            scored = []
            for r in rows:
                f = (r["f"] + 1) ** IME_ALPHA * ((r["cf"] or 0) + 1) ** (1 - IME_ALPHA) if j - i == 1 else r["f"] + 1
                sc = math.log(f / IME_TOTAL) + IME_LEN_BONUS * (j - i - 1)
                if expect and expect[i:j] == r["word"]:
                    sc += 30.0 * (j - i)
                elif hint and r["word"] in hint:
                    sc += 12.0 * (j - i)
                scored.append((r["word"], sc))
            scored.sort(key=lambda x: -x[1])
            span[(i, j)] = scored
    best = [-1e18] * (n + 1)
    back: list[tuple[int, str] | None] = [None] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        for i in range(max(0, j - IME_MAX_WORD), j):
            if best[i] <= -1e17:
                continue
            if (i, j) in span:
                w, sc = span[(i, j)][0]
                score = best[i] + sc
            elif j - i == 1:
                w, score = keys[i].replace("ˉ", ""), best[i] - 40.0  # no such syllable: leave the zhuyin
            else:
                continue
            if score > best[j]:
                best[j], back[j] = score, (i, w)
    segs = []
    j = n
    while j > 0 and back[j] is not None:
        i, w = back[j]
        segs.append({"text": w, "i": i, "j": j})
        j = i
    segs.reverse()
    cands, seen = [], set()
    for j in range(min(n, IME_MAX_WORD), 0, -1):
        for w, _ in span.get((0, j), []):
            if w not in seen:
                seen.add(w)
                cands.append({"word": w, "n": j})
    return {"best": "".join(x["text"] for x in segs), "segments": segs, "candidates": cands[:limit]}
