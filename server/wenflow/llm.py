"""Thin wrapper around the OpenAI API (chat + JSON output)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator

from . import config, db

log = logging.getLogger("wenflow.llm")
_client = None

# Shared voice for everything the model writes for the learner.
TW_STYLE = (
    "你是台灣人，說道地的台灣華語（台灣國語）。一律使用繁體中文與台灣用語"
    "（影片、軟體、計程車、捷運、網路、資訊、品質、馬鈴薯），不要使用中國大陸用語或簡體字。"
    "口語要自然，像台北人平常講話，可以適度使用語助詞（喔、啦、耶、欸、齁、吧）。"
)


def client():
    global _client
    if _client is None:
        from openai import OpenAI

        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set in .env")
        _client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=120, max_retries=2)
    return _client


def model(fast: bool = False) -> str:
    key = "llm_fast_model" if fast else "llm_model"
    return db.get_setting(key) or (config.LLM_FAST_MODEL if fast else config.LLM_MODEL)


def available() -> bool:
    return bool(config.OPENAI_API_KEY)


def chat(messages: list[dict], fast: bool = False, json_mode: bool = False, max_tokens: int | None = None) -> str:
    kwargs: dict[str, Any] = {"model": model(fast), "messages": messages}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if max_tokens:
        kwargs["max_completion_tokens"] = max_tokens
    r = client().chat.completions.create(**kwargs)
    return r.choices[0].message.content or ""


def chat_stream(messages: list[dict], fast: bool = False) -> Iterator[str]:
    stream = client().chat.completions.create(model=model(fast), messages=messages, stream=True)
    for ev in stream:
        if ev.choices and ev.choices[0].delta and ev.choices[0].delta.content:
            yield ev.choices[0].delta.content


def chat_json(system: str, user: str, fast: bool = False, history: list[dict] | None = None) -> Any:
    """Ask for a JSON object and parse it. Raises on API failure; tolerates code fences."""
    msgs = [{"role": "system", "content": system + "\n只輸出一個 JSON 物件，不要任何其他文字。"}]
    msgs += history or []
    msgs.append({"role": "user", "content": user})
    raw = chat(msgs, fast=fast, json_mode=True)
    return parse_json(raw)


def parse_json(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?|```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            return json.loads(m.group(0))
        raise
