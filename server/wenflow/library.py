"""Reading library: books (EPUB / text you supply), articles imported from the web, and Taiwanese news feeds."""
from __future__ import annotations

import json
import logging
import random
import re
import time
from collections import Counter

import httpx

from . import content_store, curriculum, db, dictionary, llm, text

log = logging.getLogger("wenflow.library")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

CHAPTER_RE = re.compile(
    r"^\s*(第\s*[一二三四五六七八九十百零〇○0-9０-９]+\s*[章回節卷部幕話集]|chapter\s+\d+|楔子|序章?|序幕|前言|自序|後記|尾聲|終章|番外.*|"
    r"[0-9０-９]{1,3}[\.、．]?|[一二三四五六七八九十]{1,3}[、．.]?)\s*[^\n]{0,30}$", re.I)


# ----------------------------------------------------------------------------------------------
# Articles
# ----------------------------------------------------------------------------------------------

def fetch_article(url: str) -> dict:
    import trafilatura

    r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=20)
    r.raise_for_status()
    html = r.text
    body = trafilatura.extract(html, include_comments=False, include_tables=False, favor_precision=True) or ""
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else "") or url
    return {"title": title.strip(), "text": body.strip(), "url": url}


def analyse(body: str) -> dict:
    words = text.segment(body)
    return text.word_difficulty(words, db.known_words())


def add_reading(title: str, body: str, source: str = "paste", url: str = "", questions: list | None = None) -> int:
    body = text.ensure_traditional(body.strip())
    title = text.ensure_traditional(title.strip()) or body[:18]
    info = analyse(body)
    return db.ex(
        "INSERT INTO readings(title,source,url,text,level,glossary,questions,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (title, source, url, body, info["level"], json.dumps(info, ensure_ascii=False),
         json.dumps(questions or [], ensure_ascii=False), db.now()))


def import_url(url: str) -> int:
    existing = db.q1("SELECT id FROM readings WHERE url=?", (url,))
    if existing:
        return existing["id"]
    art = fetch_article(url)
    if len(text.HAN_RE.findall(art["text"])) < 80:
        raise ValueError("Could not extract enough Chinese text from that page.")
    host = re.sub(r"^www\.", "", httpx.URL(url).host or "web")
    return add_reading(art["title"], art["text"], source=host, url=url)


def list_readings() -> list[dict]:
    rows = db.q("SELECT id,title,source,url,level,glossary,created_at,read_at,length(text) chars FROM readings ORDER BY id DESC")
    for r in rows:
        g = json.loads(r.pop("glossary") or "{}")
        r["coverage"] = g.get("coverage")
        r["unknown"] = len(g.get("unknown", []))
    return rows


def get_reading(rid: int) -> dict | None:
    r = db.q1("SELECT * FROM readings WHERE id=?", (rid,))
    if not r:
        return None
    r["glossary"] = json.loads(r["glossary"] or "{}")
    r["questions"] = json.loads(r["questions"] or "[]")
    r["paragraphs"] = [text.annotate(p) for p in r["text"].split("\n") if p.strip()]
    return r


def make_questions(title: str, body: str) -> list[dict]:
    """Three comprehension questions for a passage."""
    if not llm.available():
        return []
    try:
        out = llm.chat_json(
            llm.TW_STYLE + "你是華語老師，為文章出理解題。",
            "為下面的文章出 3 題選擇題（繁體中文，每題 4 個選項）。格式 {\"questions\":[{\"q\":\"…\",\"options\":[\"…\",\"…\",\"…\",\"…\"],"
            "\"answer\":0,\"explain\":\"one-sentence English explanation\"}]}\n\n標題：" + title + "\n\n" + body[:2500],
            fast=True)
        qs = []
        for q in out.get("questions", []):
            if isinstance(q.get("answer"), int) and len(q.get("options", [])) >= 2 and 0 <= q["answer"] < len(q["options"]):
                qs.append({"q": q.get("q", ""), "options": q["options"], "answer": q["answer"], "explain": q.get("explain", "")})
        return qs
    except Exception as e:  # noqa: BLE001
        log.warning("question generation failed: %s", e)
        return []


# ----------------------------------------------------------------------------------------------
# News feeds
# ----------------------------------------------------------------------------------------------

def feeds() -> list[dict]:
    return content_store.reading_sources().get("feeds", [])


def feed_entries(feed: dict, limit: int = 8) -> list[dict]:
    import feedparser

    r = httpx.get(feed["url"], headers={"User-Agent": UA}, follow_redirects=True, timeout=12)
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    out = []
    for e in parsed.entries[:limit]:
        link = e.get("link")
        if not link:
            continue
        summary = re.sub(r"<[^>]+>", "", e.get("summary", "") or "")[:160]
        out.append({"title": text.ensure_traditional(e.get("title", "")), "url": link, "summary": summary,
                    "source": feed["name"], "level": feed.get("level", 5), "category": feed.get("category", ""),
                    "published": e.get("published", "")})
    return out


def discover(max_feeds: int = 8, refresh: bool = False) -> list[dict]:
    """Recent headlines from a rotating sample of Taiwanese feeds (cached for three hours)."""
    cache = db.get_setting("news_cache") or {}
    if not refresh and cache.get("ts", 0) > time.time() - 3 * 3600 and cache.get("items"):
        return cache["items"]
    fs = [f for f in feeds() if f.get("extractable", True)]
    if not fs:
        return []
    rng = random.Random(int(time.time() // (3 * 3600)))
    rng.shuffle(fs)
    items = []
    for f in fs[:max_feeds]:
        try:
            items += feed_entries(f, 5)
        except Exception as e:  # noqa: BLE001
            log.info("feed %s failed: %s", f.get("name"), e)
    have = {r["url"] for r in db.q("SELECT url FROM readings WHERE url!=''")}
    for it in items:
        it["imported"] = it["url"] in have
    db.set_setting("news_cache", {"ts": time.time(), "items": items})
    return items


def pick_news(phase: int) -> dict | None:
    """A real article for the lesson's news block, clipped to a readable length, with questions."""
    cap = {0: 3, 1: 4, 2: 5, 3: 6, 4: 6}[phase]
    fs = [f for f in feeds() if f.get("extractable", True) and f.get("level", 5) <= cap]
    if not fs:
        return None
    random.shuffle(fs)
    have = {r["url"] for r in db.q("SELECT url FROM readings WHERE url!=''")}
    lo, hi = curriculum.READING_LEN[phase]
    deadline = time.time() + 25
    for f in fs[:4]:
        if time.time() > deadline:
            break
        try:
            entries = [e for e in feed_entries(f, 6) if e["url"] not in have]
        except Exception:  # noqa: BLE001
            continue
        for e in entries[:2]:
            if time.time() > deadline:
                break
            try:
                art = fetch_article(e["url"])
            except Exception:  # noqa: BLE001
                continue
            body = text.ensure_traditional(art["text"])
            if len(text.HAN_RE.findall(body)) < lo:
                continue
            clipped = clip(body, int(hi * 1.5))
            title = text.ensure_traditional(art["title"] or e["title"])
            qs = make_questions(title, clipped)
            rid = add_reading(title, body, source=f["name"], url=e["url"], questions=qs)
            return {"reading_id": rid, "title": title, "text": clipped, "source": f["name"], "url": e["url"],
                    "questions": qs, "clipped": len(clipped) < len(body)}
    return None


def clip(body: str, max_chars: int) -> str:
    out, n = [], 0
    for par in [p for p in body.split("\n") if p.strip()]:
        if n and n + len(par) > max_chars:
            break
        out.append(par)
        n += len(par)
    return "\n".join(out) if out else body[:max_chars]


# ----------------------------------------------------------------------------------------------
# Books
# ----------------------------------------------------------------------------------------------

def read_epub(data: bytes) -> tuple[str, str, list[tuple[str, str]]]:
    """(title, author, [(chapter title, text)]) from an EPUB file."""
    import tempfile

    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    with tempfile.NamedTemporaryFile(suffix=".epub") as f:
        f.write(data)
        f.flush()
        book = epub.read_epub(f.name, options={"ignore_ncx": True})
    title = (book.get_metadata("DC", "title") or [("", {})])[0][0]
    author = (book.get_metadata("DC", "creator") or [("", {})])[0][0]
    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for t in soup(["script", "style", "rt", "rp"]):
            t.decompose()
        head = soup.find(["h1", "h2", "h3"])
        paras = [p.get_text("", strip=True) for p in soup.find_all(["p", "div"]) if not p.find(["p", "div"])]
        body = "\n".join(p for p in paras if p) or soup.get_text("\n", strip=True)
        if len(text.HAN_RE.findall(body)) < 60:
            continue
        chapters.append(((head.get_text(strip=True) if head else "") or f"第{len(chapters) + 1}部分", body))
    return title, author, chapters


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "big5hkscs", "gb18030"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="ignore")


def split_chapters(body: str) -> list[tuple[str, str]]:
    lines = [ln.strip() for ln in body.replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln]
    marks = [i for i, ln in enumerate(lines) if len(ln) <= 36 and CHAPTER_RE.match(ln)]
    # Bare numbers only count as headings if they form a real sequence of sections.
    if len(marks) >= 3:
        chapters = []
        if marks[0] > 0:
            pre = "\n".join(lines[:marks[0]])
            if len(pre) > 200:
                chapters.append(("開頭", pre))
        for a, b in zip(marks, marks[1:] + [len(lines)]):
            seg = "\n".join(lines[a + 1:b])
            if seg.strip():
                chapters.append((lines[a], seg))
        return _merge_small(chapters)
    # No headings: cut into ~3000-character parts at paragraph breaks.
    chapters, cur, n = [], [], 0
    for ln in lines:
        cur.append(ln)
        n += len(ln)
        if n >= 3000:
            chapters.append((f"第 {len(chapters) + 1} 部分", "\n".join(cur)))
            cur, n = [], 0
    if cur:
        chapters.append((f"第 {len(chapters) + 1} 部分", "\n".join(cur)))
    return chapters


def _merge_small(chapters: list[tuple[str, str]], min_len: int = 120) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for title, body in chapters:
        if out and len(body) < min_len:
            pt, pb = out[-1]
            out[-1] = (pt, pb + "\n" + title + "\n" + body)
        else:
            out.append((title, body))
    return out


def import_book(title: str, author: str, chapters: list[tuple[str, str]], pack: str = "") -> int:
    sample = "".join(b for _, b in chapters[:5])[:4000]
    converted = text.is_simplified(sample)
    if converted:
        chapters = [(text.to_traditional(t), text.to_traditional(b)) for t, b in chapters]
        title = text.to_traditional(title)
    total = sum(len(b) for _, b in chapters)
    if not pack and ("那些年" in title or "追的女孩" in title):
        pack = "nxn"
    bid = db.ex("INSERT INTO books(title,author,added_at,meta) VALUES(?,?,?,?)",
                (title, author, db.now(), json.dumps({"pack": pack, "chars": total, "converted": converted}, ensure_ascii=False)))
    db.exmany("INSERT INTO chapters(book_id,idx,title,text) VALUES(?,?,?,?)",
              [(bid, i, t, b) for i, (t, b) in enumerate(chapters)])
    analyse_book(bid)
    if pack or not db.get_setting("active_book"):
        db.set_setting("active_book", bid)
    return bid


def analyse_book(bid: int) -> dict:
    """Vocabulary profile: coverage with what you know, and the unknown words in reading order."""
    known = db.known_words()
    learning = {r["key"] for r in db.q("SELECT key FROM cards WHERE kind='word'")}
    counts: Counter = Counter()
    first: dict[str, int] = {}
    total = 0
    pos = 0
    per_chapter = []
    for ch in db.q("SELECT id, idx, text FROM chapters WHERE book_id=? ORDER BY idx", (bid,)):
        words = [w for w in text.segment(ch["text"]) if text.HAN_RE.search(w)]
        unk = Counter()
        for w in words:
            pos += 1
            counts[w] += 1
            first.setdefault(w, pos)
            if w not in learning and not text.is_known(w, known):
                unk[w] += 1
        total += len(words)
        new_words = [w for w in unk if _teachable(w)]
        per_chapter.append((ch["id"], new_words))
    unknown = [w for w in counts if w not in learning and not text.is_known(w, known) and _teachable(w)]
    running_unknown = sum(counts[w] for w in counts if w not in learning and not text.is_known(w, known))
    # Teach in reading order, but only words that recur or are in the dictionary as common words.
    ordered = sorted((w for w in unknown if counts[w] >= 2 or dictionary.word_info(w)[0] > 300), key=lambda w: first[w])
    seen: set[str] = set()
    for cid, new_words in per_chapter:
        fresh = [w for w in new_words if w not in seen]
        seen.update(fresh)
        db.ex("UPDATE chapters SET vocab=? WHERE id=?", (json.dumps(fresh[:400], ensure_ascii=False), cid))
    stats = {"words": total, "unique": len(counts), "unknown_unique": len(unknown),
             "coverage": round(1 - running_unknown / total, 4) if total else 1.0, "teachable": len(ordered)}
    b = db.q1("SELECT meta FROM books WHERE id=?", (bid,))
    meta = json.loads(b["meta"] or "{}")
    meta["stats"] = stats
    db.ex("UPDATE books SET meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), bid))
    if db.get_setting("active_book") in (None, bid) or meta.get("pack"):
        db.set_setting("book_words", ordered[:6000])
    return stats


def _teachable(w: str) -> bool:
    if len(w) > 4 or not all(text.HAN_RE.match(c) for c in w):
        return False
    return dictionary.has_word(w)


def list_books() -> list[dict]:
    out = []
    for b in db.q("SELECT * FROM books ORDER BY id"):
        b["meta"] = json.loads(b["meta"] or "{}")
        chs = db.q("SELECT id, idx, title, length(text) chars, progress, read_at FROM chapters WHERE book_id=? ORDER BY idx", (b["id"],))
        total = sum(c["chars"] for c in chs) or 1
        b["chapters"] = chs
        b["progress"] = round(sum(c["chars"] * (c["progress"] or 0) for c in chs) / total, 4)
        b["active"] = db.get_setting("active_book") == b["id"]
        out.append(b)
    return out


def get_chapter(cid: int, start: int = 0, length: int | None = None) -> dict | None:
    ch = db.q1("SELECT c.*, b.title book_title FROM chapters c JOIN books b ON b.id=c.book_id WHERE c.id=?", (cid,))
    if not ch:
        return None
    body = ch["text"]
    end = len(body) if length is None else _para_end(body, start, length)
    part = body[start:end]
    nxt = db.q1("SELECT id FROM chapters WHERE book_id=? AND idx=?", (ch["book_id"], ch["idx"] + 1))
    prv = db.q1("SELECT id FROM chapters WHERE book_id=? AND idx=?", (ch["book_id"], ch["idx"] - 1))
    return {
        "id": cid, "book_id": ch["book_id"], "book_title": ch["book_title"], "idx": ch["idx"], "title": ch["title"],
        "start": start, "end": end, "chars": len(body), "progress": ch["progress"] or 0,
        "paragraphs": [text.annotate(p) for p in part.split("\n") if p.strip()],
        "vocab": json.loads(ch["vocab"] or "[]")[:60], "next_id": nxt and nxt["id"], "prev_id": prv and prv["id"],
    }


def _para_end(body: str, start: int, length: int) -> int:
    """End offset that finishes the paragraph in progress once `length` characters have been taken."""
    if start + length >= len(body):
        return len(body)
    nl = body.find("\n", start + length)
    return len(body) if nl < 0 or nl - start > length * 1.6 else nl + 1


def next_book_chunk(n_chars: int) -> dict | None:
    bid = db.get_setting("active_book")
    if not bid:
        return None
    ch = db.q1("SELECT c.*, b.title book_title FROM chapters c JOIN books b ON b.id=c.book_id "
               "WHERE c.book_id=? AND coalesce(c.progress,0) < 0.999 ORDER BY c.idx LIMIT 1", (bid,))
    if not ch:
        return None
    body = ch["text"]
    start = int(round((ch["progress"] or 0) * len(body)))
    # resume at a paragraph boundary
    if 0 < start < len(body) and body[start - 1] != "\n":
        nl = body.find("\n", start)
        start = len(body) if nl < 0 else nl + 1
        if start >= len(body):
            start = int(round((ch["progress"] or 0) * len(body)))
    end = _para_end(body, start, n_chars)
    part = body[start:end]
    known = db.known_words() | {r["key"] for r in db.q("SELECT key FROM cards WHERE kind='word'")}
    words = [w for w in dict.fromkeys(text.segment(part)) if text.HAN_RE.search(w) and not text.is_known(w, known) and _teachable(w)]
    words.sort(key=lambda w: dictionary.word_info(w)[0])
    from . import decks

    return {"chapter_id": ch["id"], "start": start, "end": end, "title": ch["title"], "book_title": ch["book_title"],
            "text": part, "chapter_chars": len(body), "questions": [],
            "prep": [decks.describe(w) for w in words[:10]]}


def mark_read(cid: int, end: int) -> None:
    ch = db.q1("SELECT length(text) n, progress FROM chapters WHERE id=?", (cid,))
    if not ch:
        return
    prog = max(ch["progress"] or 0, min(1.0, end / max(ch["n"], 1)))
    db.ex("UPDATE chapters SET progress=?, read_at=? WHERE id=?", (prog, db.now(), cid))


def delete_book(bid: int) -> None:
    db.ex("DELETE FROM chapters WHERE book_id=?", (bid,))
    db.ex("DELETE FROM books WHERE id=?", (bid,))
    if db.get_setting("active_book") == bid:
        db.set_setting("active_book", None)
        db.set_setting("book_words", [])


def import_book_file(filename: str, data: bytes, title: str = "", author: str = "") -> int:
    if filename.lower().endswith(".epub"):
        t, a, chapters = read_epub(data)
        return import_book(title or t or filename, author or a, chapters)
    body = decode_text(data)
    return import_book(title or re.sub(r"\.[a-z0-9]+$", "", filename, flags=re.I), author, split_chapters(body))


def import_book_text(title: str, author: str, body: str) -> int:
    return import_book(title, author, split_chapters(body))
