// Today: the daily ~30 minute session, laid out like a training programme.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Chars, Grammar, Pron, Vocab } from "../blocks/learn";
import { ReadingBlock } from "../blocks/reading";
import { Review } from "../blocks/review";
import { Conversation, Shadow } from "../blocks/speak";
import { VideoBlock } from "../blocks/video";
import { Checkpoint, Writing } from "../blocks/writing";
import { Dictation, TypingDrill, TypingResult, ZhuyinUnit } from "../blocks/zhuyin";
import { useApp } from "../store";
import { Bar, Icon, Loading, fmtTime, stopAudio } from "../ui";

function describe(b: any): string {
  const p = b.payload || {};
  switch (b.type) {
    case "review": return "Cards that are due today";
    case "zhuyin": return `Unit ${p.unit} of the zhuyin course · the rest of today builds on it`;
    case "typing": return "Type sentences with the zhuyin keyboard";
    case "dictation": return "Listen, then type what you hear";
    case "chars": return p.recall ? "Write earlier characters from memory" : [p.family && `${p.family.simplified} → ${p.family.traditional}`, p.split && `${p.split.s} splits`, `${(p.cards || []).length} characters`].filter(Boolean).join(" · ");
    case "vocab": return (p.words || []).map((w: any) => w.trad).join("　");
    case "grammar": return p.point?.title || p.point?.pattern || "";
    case "pron": return (p.items || []).map((x: any) => x.trad).join("　");
    case "reading": case "news": return p.title || "";
    case "book": return p.no_book ? `Story · ${p.title || ""}` : `${p.book_title || ""} · ${p.title || ""}`;
    case "video": return "Today's picks from Taiwanese creators";
    case "shadow": return "Repeat sentences and check your tones";
    case "conversation": return p.scenario ? `${p.scenario.title_zh} · ${p.scenario.title}` : "Role-play with the tutor";
    case "writing": return p.prompt_en || "";
    case "checkpoint": return "Ten questions on this week's material";
    default: return "";
  }
}

function BlockView({ block, onDone }: { block: any; onDone: (d?: any) => void }) {
  const p = block.payload;
  switch (block.type) {
    case "review": return <Review limit={p.limit} onDone={onDone} embedded />;
    case "zhuyin": return <ZhuyinUnit unit={p.unit} onDone={onDone} />;
    case "typing": return <TypingDrill items={p.items || []} onDone={onDone} />;
    case "dictation": return <Dictation sentences={p.sentences || []} onDone={onDone} />;
    case "chars": return <Chars payload={p} onDone={onDone} />;
    case "vocab": return <Vocab payload={p} onDone={onDone} />;
    case "grammar": return <Grammar payload={p} onDone={onDone} />;
    case "pron": return <Pron payload={p} onDone={onDone} />;
    case "reading": case "news": case "book": return <ReadingBlock payload={p} kind={block.type} onDone={onDone} />;
    case "video": return <VideoBlock payload={p} onDone={onDone} />;
    case "shadow": return <Shadow payload={p} onDone={onDone} />;
    case "conversation": return <Conversation scenarioId={p.scenario_id} twist={p.twist} turns={p.turns} onDone={onDone} />;
    case "writing": return <Writing payload={p} onDone={onDone} />;
    case "checkpoint": return <Checkpoint payload={p} onDone={onDone} />;
    default: return <div className="muted">Unknown block.</div>;
  }
}

export function Today({ day }: { day?: number }) {
  const { state, refresh } = useApp();
  const [lesson, setLesson] = useState<any>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [just, setJust] = useState<{ block: any; data: any } | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [making, setMaking] = useState(false);
  const started = useRef(Date.now());

  useEffect(() => {
    api.get(day ? `/lesson/${day}` : "/lesson/today").then(setLesson).catch((e) => setErr(e.message));
  }, [day]);

  useEffect(() => {
    if (!open) return;
    started.current = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => setElapsed((Date.now() - started.current) / 1000), 1000);
    return () => window.clearInterval(id);
  }, [open]);

  if (err)
    return (
      <div className="page narrow">
        <div className="error">{err}</div>
        <p className="muted mt8">The server could not prepare today's lesson. Check that it is running, then reload.</p>
      </div>
    );
  if (!lesson)
    return (
      <div className="page">
        <Loading label="Composing today's session" />
        <p className="center muted small">New reading, sentences and exercises are written for you each day. This takes about twenty seconds the first time.</p>
      </div>
    );

  const blocks: any[] = lesson.blocks;
  const nextBlock = blocks.find((b) => !b.done);
  const cur = blocks.find((b) => b.id === open);
  const allDone = !nextBlock;
  const phase = state?.summary?.phase_info;
  const zy = state?.zhuyin;

  const complete = async (b: any, data: any) => {
    stopAudio();
    const seconds = Math.round((Date.now() - started.current) / 1000);
    const updated = await api.post(`/lesson/${lesson.day}/block/${b.id}`, { data: { ...(data || {}), seconds } }).catch(() => null);
    if (updated) setLesson(updated);
    setJust({ block: b, data: data || {} });
    refresh();
  };
  const close = () => {
    stopAudio();
    setOpen(null);
    setJust(null);
  };
  const nextEarly = async () => {
    setMaking(true);
    try {
      setLesson(await api.post("/lesson/next"));
      refresh();
    } catch (e: any) {
      setErr(e.message);
    }
    setMaking(false);
  };

  if (open && cur) {
    const idx = blocks.indexOf(cur);
    const upcoming = blocks.find((b) => !b.done && b.id !== cur.id);
    const bare = cur.type === "video" && !just;
    return (
      <div className="stage">
        <div className="stage-top">
          <button className="icon-btn" onClick={close} title="Back to the programme">{Icon.x}</button>
          <div className="title">{cur.title}<span className="zh">{cur.title_zh}</span></div>
          <div className="grow"><Bar value={(idx + (just ? 1 : 0)) / blocks.length} /></div>
          <span className="tiny muted num upper">{idx + 1} / {blocks.length}</span>
          <span className="tiny muted num">{fmtTime(elapsed)} / {cur.minutes}:00</span>
        </div>
        <div className="stage-body">
          {just ? (
            <div className="stage-inner col gap32 center" style={{ alignItems: "center", paddingTop: 110 }}>
              <div className="eyebrow">{just.block.title} complete</div>
              <div className="zh-display" style={{ fontSize: 64 }}>{just.block.title_zh}</div>
              {just.data?.cpm != null && <TypingResult d={just.data} />}
              {just.data?.score != null && just.data?.cpm == null && <div className="muted">{Math.round(just.data.score * 100)}% correct</div>}
              {upcoming ? (
                <div className="col gap12" style={{ alignItems: "center" }}>
                  <div className="label">Up next</div>
                  <div className="h2">{upcoming.title} · {upcoming.minutes} min</div>
                  <div className="row gap12 mt16">
                    <button className="btn" onClick={close}>Programme</button>
                    <button className="btn primary lg" autoFocus onClick={() => { setJust(null); setOpen(upcoming.id); }}>Continue</button>
                  </div>
                </div>
              ) : (
                <div className="col gap12" style={{ alignItems: "center" }}>
                  <div className="h2">Session complete</div>
                  <button className="btn primary lg mt16" onClick={close}>Finish</button>
                </div>
              )}
            </div>
          ) : bare ? (
            <BlockView block={cur} onDone={(d) => complete(cur, d)} />
          ) : (
            <div className="stage-inner">
              <BlockView key={cur.id} block={cur} onDone={(d) => complete(cur, d)} />
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="hero">
        <div className="row between top wrap gap24">
          <div>
            <div className="eyebrow">Day {lesson.day} · Week {lesson.week} · {phase?.name || ""}</div>
            <h1 className="display mt16"><span className="zh">{lesson.week_title_zh}</span></h1>
            <div className="h2 mt12 muted">{lesson.week_title}</div>
          </div>
          <div className="row gap48">
            <div className="stat"><div className="v">{lesson.done_minutes}<small>/ {lesson.minutes} min</small></div><div className="l">Today</div></div>
            <div className="stat"><div className="v">{state?.summary?.streak ?? 0}</div><div className="l">Day streak</div></div>
            <div className="stat"><div className="v">{state?.srs?.due ?? 0}</div><div className="l">Cards due</div></div>
          </div>
        </div>
        <p className="prose muted mt24">{lesson.theme}</p>
        <div className="row gap16 mt32">
          {day ? <a className="btn ghost sm" href="#/" style={{ paddingLeft: 0 }}>← Today</a> : null}
          {allDone ? (
            <>
              <span className="h2">Session complete ✓</span>
              {!day && <button className="btn" onClick={nextEarly} disabled={making}>{making ? "Composing…" : "Start the next lesson early"}</button>}
            </>
          ) : (
            <button className="btn primary lg" onClick={() => setOpen(nextBlock.id)}>{lesson.done_blocks ? "Continue" : "Begin"} · {nextBlock.title}</button>
          )}
        </div>
      </div>
      <div className="row between mb16"><span className="h2">Programme</span><span className="tiny muted upper num">{lesson.done_blocks} / {blocks.length} done</span></div>
      <div className="program">
        {blocks.map((b, i) => (
          <div key={b.id} className={`block ${b.done ? "done" : ""} ${nextBlock?.id === b.id ? "next" : ""}`} onClick={() => setOpen(b.id)}>
            <span className="n">{String(i + 1).padStart(2, "0")}</span>
            <div>
              <div className="t">{b.title}<span className="zh">{b.title_zh}</span></div>
              <div className="d zh-ui">{describe(b)}</div>
            </div>
            <span className="m">{b.minutes} min</span>
            <span className="st">{b.done ? "✓" : ""}</span>
          </div>
        ))}
      </div>
      {zy && !zy.can_write && (
        <p className="small muted prose mt16">
          {zy.all_symbols
            ? "You can read every zhuyin symbol now, so readings are shown in 注音 only."
            : "Zhuyin comes first each day. Until you have met a symbol, any syllable that uses it keeps its pinyin above the character; the pinyin drops away unit by unit."}
          {" "}
          {zy.can_type
            ? `Writing your own sentences in zhuyin starts after unit ${zy.writing_from}.`
            : `Dictation starts after unit ${zy.typing_from} and writing after unit ${zy.writing_from}, once the keyboard has been taught; nothing before then asks you to type in zhuyin outside the zhuyin unit itself.`}
        </p>
      )}
      {lesson.goals?.length > 0 && (
        <div className="section mt48">
          <div className="h2 mb16">This week's goals</div>
          <div className="list">
            {lesson.goals.map((g: string, i: number) => (
              <div key={i} className="item zh-ui"><span className="idx">{String(i + 1).padStart(2, "0")}</span><span>{g}</span></div>
            ))}
          </div>
        </div>
      )}
      {state && !state.book.imported && (
        <div className="section">
          <div className="row between wrap gap16">
            <div>
              <div className="h2">那些年，我們一起追的女孩</div>
              <p className="muted small mt8 prose">The novel's vocabulary is already part of your lessons ({state.book.pack_words} words). Import your copy of the text to read it here passage by passage.</p>
            </div>
            <a className="btn" href="#/read">Import the book</a>
          </div>
        </div>
      )}
    </div>
  );
}
