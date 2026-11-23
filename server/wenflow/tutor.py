"""The AI conversation tutor: role-play scenarios with a Taiwanese partner, per-turn feedback on
naturalness and tones, hints, and an end-of-session summary."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator

from . import content_store, curriculum, db, llm, text

log = logging.getLogger("wenflow.tutor")
_pool = ThreadPoolExecutor(max_workers=6)

FREE_TALK = {
    "id": "free", "title": "Free talk", "title_zh": "自由聊天", "level": 3,
    "setting": "A relaxed chat over drinks at a 手搖飲 shop in Taipei.",
    "ai_role": "小安, a friendly Taipei local in their late twenties who is curious, funny and talks the way young Taiwanese really talk.",
    "learner_role": "Yourself.",
    "goals": ["Keep the conversation going for several turns", "Ask at least two questions back", "Use one new word from this week"],
    "opening_line": "欸，你來啦！最近過得怎麼樣？",
}


def scenario_list() -> list[dict]:
    done = {r["scenario_id"]: r["n"] for r in db.q("SELECT scenario_id, count(*) n FROM conversations GROUP BY scenario_id")}
    out = [{**{k: FREE_TALK[k] for k in ("id", "title", "title_zh", "level", "setting", "goals")}, "times": done.get("free", 0)}]
    for s in content_store.scenarios():
        out.append({**{k: s.get(k) for k in ("id", "title", "title_zh", "level", "setting", "goals")},
                    "times": done.get(s["id"], 0)})
    return out


def _scenario(sid: str | None) -> dict:
    if not sid or sid == "free":
        return FREE_TALK
    return content_store.scenario(sid) or FREE_TALK


def _persona(sc: dict, twist: bool, topic: str = "") -> str:
    goals = "；".join(f"({i}) {g}" for i, g in enumerate(sc.get("goals", [])))
    extra = ""
    if twist:
        extra += "\n- 在對話中段自然地加入一個小狀況（例如缺貨、聽錯、臨時改變），讓對方需要多解釋或協調。"
    if topic:
        extra += f"\n- 盡量把話題帶到：{topic}。"
    return (
        llm.TW_STYLE + "\n你正在和一位中文學習者做角色扮演的口說練習。\n"
        f"場景：{sc.get('setting', '')}\n你的角色：{sc.get('ai_role', '')}\n對方的角色：{sc.get('learner_role', '')}\n"
        f"對方要完成的目標：{goals}\n"
        "規則：\n"
        "- 完全以角色的身份說話，用道地、口語的台灣說法。每次只說 1 到 3 句（最多 60 個字），並且推動對話往下走。\n"
        "- 不要糾正對方的中文，不要跳出角色，不要說英文，不要用表情符號或括號說明。\n"
        "- 對方的話是語音辨識的結果，可能有同音錯字，請依照情境理解。如果真的聽不懂，就像真人一樣請他再說一次。\n"
        "- 對方完成所有目標之後，自然地結束對話。" + extra + "\n"
        "輸出 JSON：{\"reply\":\"你說的話\",\"en\":\"natural English translation\",\"goals_done\":[已完成目標的編號],\"ended\":false}"
    )


def _coach_system() -> str:
    return (
        llm.TW_STYLE + "\n你是一位台灣的華語老師，正在看一位學習者在口說練習中說的一句話。"
        "學習者原本學的是中國大陸的普通話，現在想說得像台灣人。那句話來自語音辨識，可能有同音錯字——"
        "不要把明顯的辨識錯字當成學習者的錯誤。\n"
        "請判斷並輸出 JSON：{\n"
        "\"ok\": 這句話是否正確而且自然（true/false）,\n"
        "\"corrected\": \"只修正文法或用詞錯誤的最小改動版本；如果沒有錯就給空字串\",\n"
        "\"natural\": \"台灣人在這個情境下最自然的說法（同樣的意思，可以加語助詞）\",\n"
        "\"note\": \"one or two short English sentences on the most useful difference: mainland vs Taiwan wording, particles, register or grammar\",\n"
        "\"issues\": [{\"type\":\"mainland-term|grammar|word-choice|register|unclear\",\"said\":\"…\",\"better\":\"…\",\"why\":\"short English\"}],\n"
        "\"praise\": \"a few words of specific English praise, or empty\"\n}\n"
        "如果原句已經很道地，natural 可以和原句相同，issues 給空陣列。不要捏造問題。"
    )


def start(scenario_id: str | None, twist: bool = False, topic: str = "") -> dict:
    sc = _scenario(scenario_id)
    opening = sc.get("opening_line") or "你好！"
    msgs = [{"role": "assistant", "zh": opening}]
    cid = db.ex("INSERT INTO conversations(scenario_id,started_at,messages,summary) VALUES(?,?,?,?)",
                (sc["id"], db.now(), json.dumps(msgs, ensure_ascii=False),
                 json.dumps({"twist": twist, "topic": topic, "goals_done": []}, ensure_ascii=False)))
    return {
        "id": cid,
        "scenario": {k: sc.get(k) for k in ("id", "title", "title_zh", "setting", "ai_role", "learner_role", "goals",
                                             "key_phrases", "native_tips", "level")},
        "opening": {"zh": opening, "tokens": text.annotate(opening)},
    }


def _load(cid: int) -> tuple[dict, list[dict], dict]:
    row = db.q1("SELECT * FROM conversations WHERE id=?", (cid,))
    if not row:
        raise KeyError(cid)
    return row, json.loads(row["messages"] or "[]"), json.loads(row["summary"] or "{}")


def _save(cid: int, msgs: list[dict], state: dict) -> None:
    db.ex("UPDATE conversations SET messages=?, summary=? WHERE id=?",
          (json.dumps(msgs, ensure_ascii=False), json.dumps(state, ensure_ascii=False), cid))


def _history(msgs: list[dict]) -> list[dict]:
    out = []
    for m in msgs[-16:]:
        if m["role"] == "assistant":
            out.append({"role": "assistant", "content": json.dumps({"reply": m["zh"]}, ensure_ascii=False)})
        else:
            out.append({"role": "user", "content": m["zh"]})
    return out


def _reply(sc: dict, state: dict, msgs: list[dict], said: str) -> dict:
    out = llm.chat_json(_persona(sc, state.get("twist", False), state.get("topic", "")), said, history=_history(msgs))
    reply = text.ensure_traditional(str(out.get("reply", "")).strip()) or "不好意思，可以再說一次嗎？"
    done = [g for g in out.get("goals_done", []) if isinstance(g, int)]
    return {"zh": reply, "en": str(out.get("en", "")), "goals_done": done, "ended": bool(out.get("ended"))}


def _coach(sc: dict, last_ai: str, said: str) -> dict:
    user = json.dumps({"scene": sc.get("title_zh") or sc.get("title"), "partner_said": last_ai, "learner_said": said},
                      ensure_ascii=False)
    out = llm.chat_json(_coach_system(), user, fast=True)
    res = {
        "ok": bool(out.get("ok")),
        "corrected": text.ensure_traditional(str(out.get("corrected") or "")),
        "natural": text.ensure_traditional(str(out.get("natural") or "")),
        "note": str(out.get("note") or ""),
        "praise": str(out.get("praise") or ""),
        "issues": [],
    }
    for it in out.get("issues") or []:
        if isinstance(it, dict) and it.get("better"):
            res["issues"].append({"type": str(it.get("type", "")), "said": text.ensure_traditional(str(it.get("said", ""))),
                                  "better": text.ensure_traditional(str(it["better"])), "why": str(it.get("why", ""))})
    if res["natural"]:
        res["natural_tokens"] = text.annotate(res["natural"])
    return res


def _tone_report(audio, asr: dict) -> dict:
    from . import speech

    r = speech.analyze_tones(audio, None, asr)
    syl = [{k: s.get(k) for k in ("c", "py", "expected", "detected", "ok", "sure", "contour")} for s in r.get("syllables", [])]
    wrong = [s for s in syl if s["ok"] is False and s.get("sure")]
    return {"score": r.get("score"), "graded": r.get("graded") or 0, "syllables": syl, "wrong": len(wrong),
            "median_hz": r.get("median_hz")}


def turn(cid: int, audio_bytes: bytes | None, typed: str | None) -> Iterator[dict]:
    """One exchange. Yields events as they are ready: asr, tones, reply, feedback, done."""
    row, msgs, state = _load(cid)
    sc = _scenario(row["scenario_id"])
    audio = asr = None
    if audio_bytes:
        from . import speech

        try:
            audio = speech.decode_audio(audio_bytes)
        except Exception as e:  # noqa: BLE001
            yield {"type": "error", "message": f"Could not read the recording ({e})."}
            return
        if len(audio) < speech.SR * 0.4:
            yield {"type": "error", "message": "That recording was too short — hold the button while you speak."}
            return
        asr = speech.transcribe(audio)
        said = asr["text"].strip()
    else:
        said = text.ensure_traditional((typed or "").strip())
    if not said:
        yield {"type": "error", "message": "I couldn't hear any speech. Try again a little closer to the microphone."}
        return
    yield {"type": "asr", "text": said, "tokens": text.annotate(said), "spoken": bool(audio_bytes)}

    last_ai = next((m["zh"] for m in reversed(msgs) if m["role"] == "assistant"), "")
    futures = {_pool.submit(_reply, sc, state, msgs, said): "reply", _pool.submit(_coach, sc, last_ai, said): "feedback"}
    if audio is not None and asr and asr.get("chars"):
        futures[_pool.submit(_tone_report, audio, asr)] = "tones"
    user_msg: dict = {"role": "user", "zh": said, "spoken": bool(audio_bytes)}
    ai_msg: dict | None = None
    for fut in as_completed(futures):
        kind = futures[fut]
        try:
            res = fut.result()
        except Exception as e:  # noqa: BLE001
            log.warning("tutor %s failed: %s", kind, e)
            if kind == "reply":
                yield {"type": "error", "message": f"The tutor could not reply ({str(e)[:160]})."}
            continue
        if kind == "reply":
            ai_msg = {"role": "assistant", "zh": res["zh"], "en": res["en"]}
            state["goals_done"] = sorted(set(state.get("goals_done", [])) | set(res["goals_done"]))
            state["ended"] = res["ended"]
            yield {"type": "reply", "zh": res["zh"], "en": res["en"], "tokens": text.annotate(res["zh"]),
                   "goals_done": state["goals_done"], "ended": res["ended"]}
        elif kind == "feedback":
            user_msg["feedback"] = {k: v for k, v in res.items() if k != "natural_tokens"}
            yield {"type": "feedback", **res}
        else:
            user_msg["tones"] = {"score": res["score"], "wrong": res["wrong"], "graded": res["graded"]}
            yield {"type": "tones", **res}
    msgs.append(user_msg)
    if ai_msg:
        msgs.append(ai_msg)
    _save(cid, msgs, state)
    turns = sum(1 for m in msgs if m["role"] == "user")
    yield {"type": "done", "turns": turns, "goals_done": state.get("goals_done", []), "ended": state.get("ended", False)}


def hint(cid: int) -> dict:
    """Three natural ways a Taiwanese speaker might answer right now."""
    row, msgs, state = _load(cid)
    sc = _scenario(row["scenario_id"])
    convo = "\n".join(("對方：" if m["role"] == "assistant" else "我：") + m["zh"] for m in msgs[-8:])
    out = llm.chat_json(
        llm.TW_STYLE + "\n你在幫一位學習者想下一句要怎麼回。給三個台灣人會說的回答：一個簡短隨性（10 個字以內）、一個標準禮貌、一個用到道地說法或語助詞的。每個回答最多 28 個字，只回應對方剛剛說的話。"
        "輸出 JSON：{\"options\":[{\"zh\":\"…\",\"en\":\"…\",\"note\":\"short English note on tone/register\"}]}",
        json.dumps({"scene": sc.get("setting"), "my_role": sc.get("learner_role"), "my_goals": sc.get("goals"),
                    "conversation": convo}, ensure_ascii=False), fast=True)
    opts = []
    for o in out.get("options", [])[:3]:
        if isinstance(o, dict) and o.get("zh"):
            zh = text.ensure_traditional(str(o["zh"]))
            opts.append({"zh": zh, "en": str(o.get("en", "")), "note": str(o.get("note", "")), "tokens": text.annotate(zh)})
    return {"options": opts}


def finish(cid: int) -> dict:
    row, msgs, state = _load(cid)
    sc = _scenario(row["scenario_id"])
    user_turns = [m for m in msgs if m["role"] == "user"]
    if not user_turns:
        return {"summary": "No turns yet.", "did_well": [], "work_on": [], "phrases": [], "turns": 0}
    if state.get("report"):
        return state["report"]
    convo = "\n".join(("夥伴：" if m["role"] == "assistant" else "學習者：") + m["zh"] for m in msgs)
    try:
        out = llm.chat_json(
            llm.TW_STYLE + "\n你是台灣的華語老師，為一段口說練習寫回饋。學習者想說得像台灣人。"
            "輸出 JSON：{\"summary\":\"2-3 English sentences on how it went\",\"did_well\":[\"English, specific\"],"
            "\"work_on\":[\"English, specific and actionable\"],"
            "\"phrases\":[{\"zh\":\"值得記住的道地說法（來自夥伴的話或更好的說法）\",\"en\":\"…\",\"why\":\"short English\"}]}"
            "，phrases 給 4 到 6 個。",
            json.dumps({"scene": sc.get("title"), "goals": sc.get("goals"), "transcript": convo}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        log.warning("summary failed: %s", e)
        out = {"summary": "Session saved.", "did_well": [], "work_on": [], "phrases": []}
    phrases = []
    for p in out.get("phrases", [])[:6]:
        if isinstance(p, dict) and p.get("zh"):
            zh = text.ensure_traditional(str(p["zh"]))
            phrases.append({"zh": zh, "en": str(p.get("en", "")), "why": str(p.get("why", "")), "tokens": text.annotate(zh, False)})
    toned = [m["tones"] for m in user_turns if m.get("tones")]
    report = {
        "summary": str(out.get("summary", "")), "did_well": [str(x) for x in out.get("did_well", [])][:4],
        "work_on": [str(x) for x in out.get("work_on", [])][:4], "phrases": phrases, "turns": len(user_turns),
        "goals": sc.get("goals", []), "goals_done": state.get("goals_done", []),
        "tone_slips": sum(t.get("wrong", 0) for t in toned), "tone_graded": sum(t.get("graded", 0) for t in toned),
    }
    state["report"] = report
    _save(cid, msgs, state)
    db.log_activity("conversation", len(user_turns) * 60, {"scenario": sc["id"], "conversation": cid})
    return report


def history(limit: int = 30) -> list[dict]:
    rows = db.q("SELECT id, scenario_id, started_at, messages, summary FROM conversations ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        msgs = json.loads(r["messages"] or "[]")
        st = json.loads(r["summary"] or "{}")
        sc = _scenario(r["scenario_id"])
        out.append({"id": r["id"], "scenario_id": r["scenario_id"], "title": sc.get("title"), "title_zh": sc.get("title_zh"),
                    "started_at": r["started_at"], "turns": sum(1 for m in msgs if m["role"] == "user"),
                    "report": st.get("report")})
    return out


def weekly_topic() -> str:
    from . import lessons

    info = curriculum.position(max(lessons.current_day(), 1))["info"]
    return info.get("title_zh", "")
