"""Spaced repetition (SM-2 variant with Again/Hard/Good/Easy grades and learning steps)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import db

LEARNING_STEPS_MIN = [1, 10]  # minutes


def add_card(kind: str, key: str, data: dict, source: str = "", due: datetime | None = None) -> int | None:
    existing = db.q1("SELECT id FROM cards WHERE kind=? AND key=?", (kind, key))
    if existing:
        return existing["id"]
    return db.ex(
        "INSERT INTO cards(kind,key,data,due,created_at,source) VALUES(?,?,?,?,?,?)",
        (kind, key, json.dumps(data, ensure_ascii=False), (due or datetime.now()).isoformat(timespec="seconds"),
         db.now(), source),
    )


def due_cards(limit: int = 50, kinds: list[str] | None = None) -> list[dict]:
    now = datetime.now().isoformat(timespec="seconds")
    sql = "SELECT * FROM cards WHERE due<=?"
    args: list = [now]
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        args += kinds
    sql += " ORDER BY reps=0, due LIMIT ?"
    args.append(limit)
    rows = db.q(sql, tuple(args))
    for r in rows:
        r["data"] = json.loads(r["data"])
    return rows


def counts() -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    r = db.q1(
        "SELECT count(*) total, sum(due<=?) due, sum(reps=0) new, sum(interval>=21) mature FROM cards", (now,)
    )
    return {k: (v or 0) for k, v in r.items()}


def review(card_id: int, grade: int, mode: str = "") -> dict:
    """grade: 1 again, 2 hard, 3 good, 4 easy."""
    c = db.q1("SELECT * FROM cards WHERE id=?", (card_id,))
    if not c:
        raise KeyError(card_id)
    now = datetime.now()
    interval, ease, reps, lapses = c["interval"], c["ease"], c["reps"], c["lapses"]
    if grade == 1:
        lapses += 1 if reps > 0 else 0
        reps = 0
        ease = max(1.3, ease - 0.2)
        interval = 0
        due = now + timedelta(minutes=LEARNING_STEPS_MIN[0])
    elif interval < 1:  # learning phase
        if grade == 2:
            due = now + timedelta(minutes=LEARNING_STEPS_MIN[-1])
        else:
            interval = 1 if grade == 3 else 4
            due = now + timedelta(days=interval)
        reps += 1
    else:
        if grade == 2:
            interval = max(1.0, interval * 1.2)
            ease = max(1.3, ease - 0.15)
        elif grade == 3:
            interval = interval * ease
        else:
            interval = interval * ease * 1.3
            ease += 0.15
        reps += 1
        due = now + timedelta(days=interval)
    db.ex(
        "UPDATE cards SET interval=?, ease=?, reps=?, lapses=?, due=?, last_review=? WHERE id=?",
        (interval, ease, reps, lapses, due.isoformat(timespec="seconds"), now.isoformat(timespec="seconds"), card_id),
    )
    db.ex("INSERT INTO reviews(card_id,ts,grade,mode) VALUES(?,?,?,?)", (card_id, db.now(), grade, mode))
    if c["kind"] == "word" and interval >= 21:
        db.ex("INSERT INTO words(word,status,source,added_at) VALUES(?,?,?,?) ON CONFLICT(word) DO UPDATE SET status='known'",
              (c["key"], "known", "srs", db.now()))
    return {"id": card_id, "due": due.isoformat(timespec="seconds"), "interval": interval}
