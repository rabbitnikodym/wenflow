"""Application state in SQLite (data/app.sqlite)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime
from typing import Any

from .config import APP_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS words(
  word TEXT PRIMARY KEY, status TEXT NOT NULL, source TEXT, added_at TEXT);
CREATE TABLE IF NOT EXISTS cards(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL,
  due TEXT NOT NULL, interval REAL DEFAULT 0, ease REAL DEFAULT 2.5, reps INTEGER DEFAULT 0,
  lapses INTEGER DEFAULT 0, last_review TEXT, created_at TEXT, source TEXT,
  UNIQUE(kind, key));
CREATE INDEX IF NOT EXISTS ix_cards_due ON cards(due);
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, card_id INTEGER, ts TEXT, grade INTEGER, mode TEXT);
CREATE TABLE IF NOT EXISTS lessons(
  day INTEGER PRIMARY KEY, date TEXT, plan TEXT, progress TEXT DEFAULT '{}', status TEXT DEFAULT 'new',
  generated_at TEXT);
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, ts TEXT, day TEXT, kind TEXT, seconds INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS videos(
  id TEXT PRIMARY KEY, title TEXT, channel TEXT, url TEXT, duration REAL, thumbnail TEXT,
  source TEXT, caption_source TEXT, level INTEGER, coverage REAL, tw_score REAL,
  captions TEXT, status TEXT DEFAULT 'new', recommended_on TEXT, added_at TEXT, watched_at TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS books(id INTEGER PRIMARY KEY, title TEXT, author TEXT, added_at TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS chapters(
  id INTEGER PRIMARY KEY, book_id INTEGER, idx INTEGER, title TEXT, text TEXT,
  vocab TEXT, read_at TEXT, progress REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS readings(
  id INTEGER PRIMARY KEY, title TEXT, source TEXT, url TEXT, text TEXT, level INTEGER,
  glossary TEXT, questions TEXT, created_at TEXT, read_at TEXT);
CREATE TABLE IF NOT EXISTS conversations(
  id INTEGER PRIMARY KEY, scenario_id TEXT, started_at TEXT, messages TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS typing_stats(id INTEGER PRIMARY KEY, ts TEXT, mode TEXT, chars INTEGER,
  seconds REAL, accuracy REAL);
"""

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(APP_DB, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        _local.c = c
    return c


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


def q(sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql: str, args: tuple = ()) -> dict | None:
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None


def ex(sql: str, args: tuple = ()) -> int:
    c = conn()
    cur = c.execute(sql, args)
    c.commit()
    return cur.lastrowid


def exmany(sql: str, rows: list[tuple]) -> None:
    c = conn()
    c.executemany(sql, rows)
    c.commit()


def get_setting(key: str, default: Any = None) -> Any:
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return json.loads(r["value"]) if r else default


def set_setting(key: str, value: Any) -> None:
    ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, json.dumps(value, ensure_ascii=False)))


def log_activity(kind: str, seconds: int = 0, detail: Any = None) -> None:
    ex("INSERT INTO activity(ts,day,kind,seconds,detail) VALUES(?,?,?,?,?)",
       (now(), today(), kind, seconds, json.dumps(detail, ensure_ascii=False) if detail is not None else None))


def known_words() -> set[str]:
    return {r["word"] for r in q("SELECT word FROM words WHERE status='known'")}
