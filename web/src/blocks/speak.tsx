// Speaking blocks: shadowing with tone feedback, and the conversation tutor.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Tokens } from "../han";
import { ZhuyinInput } from "../ime";
import { MicButton, ShadowLine, ToneReport } from "../speech";
import { useApp } from "../store";
import { Bar, Icon, Loading, Speak, say, stopAudio } from "../ui";

export function Shadow({ payload, onDone }: { payload: any; onDone: (d?: any) => void }) {
  const sentences: any[] = payload.sentences || [];
  const [i, setI] = useState(0);
  const [scores, setScores] = useState<number[]>([]);
  const s = sentences[i];
  useEffect(() => {
    if (s) say(s.zh);
  }, [s]);
  if (!s) return null;
  const next = () => {
    if (i + 1 >= sentences.length) onDone({ score: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null });
    else setI(i + 1);
  };
  return (
    <div className="col gap24">
      <div className="row between"><span className="label">Listen, then say it</span><span className="tiny muted num">{i + 1} / {sentences.length}</span></div>
      <Bar value={i / sentences.length} />
      {payload.focus && i === 0 && <p className="small muted prose">This week: {payload.focus}</p>}
      <ShadowLine zh={s.zh} en={s.en} tokens={s.tokens} onResult={(sc) => sc != null && setScores((x) => [...x, sc])} />
      <div className="row end">
        <button className="btn primary" onClick={next}>{i + 1 >= sentences.length ? "Done" : "Next sentence"}</button>
      </div>
    </div>
  );
}

interface Msg {
  role: "ai" | "me";
  zh: string;
  en?: string;
  tokens?: any[];
  feedback?: any;
  tones?: any;
  spoken?: boolean;
  pending?: boolean;
}

/** A full role-play conversation. `turns` is the suggested length; the learner can end at any time. */
export function Conversation({ scenarioId, twist, turns = 6, onDone, topic }: { scenarioId?: string; twist?: boolean; turns?: number; topic?: string; onDone?: (d?: any) => void }) {
  const { toast } = useApp();
  const [conv, setConv] = useState<any>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [mode, setMode] = useState<"voice" | "text">("voice");
  const [typed, setTyped] = useState("");
  const [hints, setHints] = useState<any[] | null>(null);
  const [hintBusy, setHintBusy] = useState(false);
  const [goals, setGoals] = useState<number[]>([]);
  const [count, setCount] = useState(0);
  const [report, setReport] = useState<any>(null);
  const [ending, setEnding] = useState(false);
  const [showEn, setShowEn] = useState(false);
  const [brief, setBrief] = useState(true);
  const [handsFree, setHandsFree] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    api.post("/tutor/start", { scenario_id: scenarioId || null, twist: !!twist, topic: topic || "" }).then((c) => {
      if (!live) return;
      setConv(c);
      setMsgs([{ role: "ai", zh: c.opening.zh, tokens: c.opening.tokens }]);
    }).catch((e) => setErr(e.message));
    return () => {
      live = false;
      stopAudio();
    };
  }, [scenarioId, twist, topic]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, hints, busy]);

  const begin = () => {
    setBrief(false);
    if (conv) say(conv.opening.zh);
  };

  const send = async (blob: Blob | null, text?: string) => {
    if (!conv || busy) return;
    setBusy(true);
    setErr("");
    setHints(null);
    const f = new FormData();
    if (blob) f.append("audio", blob, "speech.webm");
    if (text) f.append("text", text);
    let mine = -1;
    try {
      await api.stream(`/tutor/${conv.id}/turn`, f, (ev) => {
        if (ev.type === "asr") {
          setMsgs((m) => {
            mine = m.length;
            return [...m, { role: "me", zh: ev.text, tokens: ev.tokens, spoken: ev.spoken, pending: true }];
          });
        } else if (ev.type === "tones") {
          setMsgs((m) => m.map((x, i) => (i === mine ? { ...x, tones: ev } : x)));
        } else if (ev.type === "feedback") {
          setMsgs((m) => m.map((x, i) => (i === mine ? { ...x, feedback: ev, pending: false } : x)));
        } else if (ev.type === "reply") {
          setMsgs((m) => [...m, { role: "ai", zh: ev.zh, en: ev.en, tokens: ev.tokens }]);
          setGoals(ev.goals_done || []);
          say(ev.zh);
        } else if (ev.type === "done") {
          setCount(ev.turns);
        } else if (ev.type === "error") {
          setErr(ev.message);
        }
      });
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy(false);
  };

  const hint = async () => {
    if (!conv) return;
    setHintBusy(true);
    try {
      setHints((await api.post(`/tutor/${conv.id}/hint`)).options);
    } catch (e: any) {
      toast(e.message);
    }
    setHintBusy(false);
  };

  const finish = async () => {
    if (!conv) return;
    stopAudio();
    setEnding(true);
    try {
      setReport(await api.post(`/tutor/${conv.id}/finish`));
    } catch (e: any) {
      setErr(e.message);
    }
    setEnding(false);
  };

  if (err && !conv) return <div className="error">{err}</div>;
  if (!conv) return <Loading label="Setting the scene" />;
  const sc = conv.scenario;

  if (report) {
    return (
      <div className="col gap32">
        <div>
          <div className="eyebrow">Conversation review</div>
          <h1 className="h1 mt8">{sc.title}</h1>
        </div>
        <div className="row gap48 wrap">
          <div className="stat"><div className="v">{report.turns}</div><div className="l">Turns</div></div>
          <div className="stat"><div className="v">{(report.goals_done || []).length}<small>/ {(report.goals || []).length}</small></div><div className="l">Goals met</div></div>
          {report.tone_graded > 0 && <div className="stat"><div className="v">{report.tone_slips}<small>/ {report.tone_graded}</small></div><div className="l">Clear tone slips</div></div>}
        </div>
        <p className="prose" style={{ fontSize: 16 }}>{report.summary}</p>
        <div className="grid2">
          <div>
            <div className="label mb8">What went well</div>
            <ul className="prose small" style={{ paddingLeft: 18, margin: 0 }}>{(report.did_well || []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
          </div>
          <div>
            <div className="label mb8">Work on</div>
            <ul className="prose small" style={{ paddingLeft: 18, margin: 0 }}>{(report.work_on || []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
          </div>
        </div>
        {report.phrases?.length > 0 && (
          <div>
            <div className="label mb8">Native phrases worth keeping</div>
            <div className="list">
              {report.phrases.map((p: any, i: number) => (
                <PhraseRow key={i} p={p} />
              ))}
            </div>
          </div>
        )}
        {onDone && <div className="row end"><button className="btn primary lg" onClick={() => onDone({ turns: report.turns, tone_slips: report.tone_slips })}>Done</button></div>}
      </div>
    );
  }

  if (brief)
    return (
      <div className="col gap32">
        <div>
          <div className="eyebrow">Role-play · level {sc.level}</div>
          <h1 className="h1 mt8">{sc.title}</h1>
          <div className="zh mt8" style={{ fontSize: 26 }}>{sc.title_zh}</div>
        </div>
        <p className="prose zh-ui" style={{ fontSize: 16 }}>{sc.setting}</p>
        <div className="grid2">
          <div><div className="label mb8">Your partner</div><p className="small muted zh-ui">{sc.ai_role}</p></div>
          <div><div className="label mb8">You</div><p className="small muted zh-ui">{sc.learner_role}</p></div>
        </div>
        <div>
          <div className="label mb8">Goals</div>
          <div className="list">{(sc.goals || []).map((g: string, i: number) => <div key={i} className="item zh-ui"><span className="idx">{String(i + 1).padStart(2, "0")}</span>{g}</div>)}</div>
        </div>
        {sc.key_phrases?.length > 0 && (
          <div>
            <div className="label mb8">Useful phrases</div>
            <div className="list">
              {sc.key_phrases.slice(0, 8).map((p: any, i: number) => (
                <div key={i} className="item top">
                  <div className="grow">
                    <div className="han" style={{ fontSize: 21 }}>{p.zh}</div>
                    <div className="small muted">{p.en}</div>
                    {p.note && <div className="tiny faint mt4 zh-ui">{p.note}</div>}
                  </div>
                  <Speak text={p.zh} />
                </div>
              ))}
            </div>
          </div>
        )}
        {sc.native_tips?.length > 0 && (
          <div>
            <div className="label mb8">Local knowledge</div>
            <ul className="small muted prose zh-ui" style={{ paddingLeft: 18, margin: 0 }}>{sc.native_tips.map((t: string, i: number) => <li key={i}>{t}</li>)}</ul>
          </div>
        )}
        <div className="row end"><button className="btn primary lg" onClick={begin}>Start talking</button></div>
      </div>
    );

  return (
    <div className="col gap24">
      <div className="row between wrap gap12">
        <div>
          <div className="eyebrow">{sc.title_zh}</div>
          <div className="h2 mt4">{sc.title}</div>
        </div>
        <div className="row gap8">
          <button className={`btn sm ${showEn ? "on" : ""}`} onClick={() => setShowEn((x) => !x)}>English</button>
          <button className="btn sm" onClick={finish} disabled={ending || count === 0}>{ending ? "Reviewing…" : "End & review"}</button>
        </div>
      </div>
      <div className="row wrap gap8">
        {(sc.goals || []).map((g: string, i: number) => (
          <span key={i} className={`chip ${goals.includes(i) ? "solid" : ""}`} style={{ height: "auto", padding: "4px 9px", whiteSpace: "normal", textTransform: "none", letterSpacing: ".02em", fontWeight: 500, fontSize: 12 }}>
            {goals.includes(i) ? "✓ " : ""}{g}
          </span>
        ))}
      </div>
      <hr />
      <div className="chat">
        {msgs.map((m, i) =>
          m.role === "ai" ? (
            <div key={i} className="msg ai">
              <div className="who">Partner</div>
              <div className="row gap8 top">
                {m.tokens ? <Tokens tokens={m.tokens} /> : <div className="han-text">{m.zh}</div>}
                <Speak text={m.zh} />
              </div>
              {showEn && m.en && <div className="en">{m.en}</div>}
            </div>
          ) : (
            <div key={i} className="msg me">
              <div className="who">You {m.spoken ? "· heard as" : ""}</div>
              {m.tokens ? <Tokens tokens={m.tokens} size="s" /> : <div className="han-text s">{m.zh}</div>}
              {m.tones?.syllables?.length > 0 && (
                <div className="mt12"><ToneReport syllables={m.tones.syllables} score={m.tones.score} compact /></div>
              )}
              {m.pending && <div className="tiny faint mt8">checking…</div>}
              {m.feedback && <Feedback fb={m.feedback} said={m.zh} />}
            </div>
          ),
        )}
        {busy && msgs[msgs.length - 1]?.role === "me" && <div className="msg ai"><span className="spinner" /></div>}
        {hints && (
          <div className="fb">
            <div className="label mb8">Ways a Taiwanese speaker might answer</div>
            {hints.map((h, i) => (
              <div key={i} className="mt8">
                <div className="row gap8"><Tokens tokens={h.tokens} size="s" /><Speak text={h.zh} /></div>
                <div className="small muted">{h.en}{h.note ? ` — ${h.note}` : ""}</div>
              </div>
            ))}
          </div>
        )}
        <div ref={bottom} />
      </div>
      {err && <div className="error">{err}</div>}
      <div className="stage-foot" style={{ marginTop: 8 }}>
        <div className="row gap8">
          <button className="btn sm" onClick={hint} disabled={hintBusy || busy}>{hintBusy ? "…" : "Hint"}</button>
          <button className="btn sm" onClick={() => setMode(mode === "voice" ? "text" : "voice")}>{mode === "voice" ? "Type instead" : "Speak instead"}</button>
          {mode === "voice" && <button className={`btn sm ${handsFree ? "on" : ""}`} onClick={() => setHandsFree((x) => !x)} title="Listen continuously: speak, pause, and it replies">Hands-free</button>}
        </div>
        {mode === "voice" ? (
          <MicButton onAudio={(b) => send(b)} busy={busy} handsFree={handsFree} />
        ) : (
          <div className="grow row gap8 top" style={{ maxWidth: 560 }}>
            <ZhuyinInput className="grow" value={typed} onChange={setTyped} rows={1} autoFocus onEnter={() => { if (typed.trim()) { send(null, typed.trim()); setTyped(""); } }} placeholder="Type your reply…" />
            <button className="btn primary" disabled={busy || !typed.trim()} onClick={() => { send(null, typed.trim()); setTyped(""); }}>Send</button>
          </div>
        )}
        <span className="tiny muted num upper">{count} / {turns} turns</span>
      </div>
    </div>
  );
}

function Feedback({ fb, said }: { fb: any; said: string }) {
  const same = !fb.natural || fb.natural.replace(/[，。！？、\s]/g, "") === said.replace(/[，。！？、\s]/g, "");
  if (fb.ok && same && !fb.issues?.length) return fb.praise ? <div className="tiny muted mt8">✓ {fb.praise}</div> : <div className="tiny muted mt8 upper">Natural ✓</div>;
  return (
    <div className="fb">
      {!same && (
        <>
          <div className="label">More natural in Taiwan</div>
          <div className="row gap8 top mt4">
            {fb.natural_tokens ? <Tokens tokens={fb.natural_tokens} size="s" className="nat" /> : <div className="nat">{fb.natural}</div>}
            <Speak text={fb.natural} />
          </div>
        </>
      )}
      {fb.corrected && fb.corrected !== fb.natural && fb.corrected !== said && (
        <div className="mt8"><span className="label">Corrected</span> <span className="zh" style={{ fontSize: 17 }}>{fb.corrected}</span></div>
      )}
      {fb.note && <div className="muted mt8">{fb.note}</div>}
      {(fb.issues || []).map((it: any, i: number) => (
        <div key={i} className="issue">
          <span className="zh strike">{it.said}</span>
          <span><span className="zh" style={{ fontSize: 16 }}>{it.better}</span> <span className="muted">— {it.why}</span></span>
        </div>
      ))}
      {fb.praise && <div className="tiny faint mt8">{fb.praise}</div>}
    </div>
  );
}

function PhraseRow({ p }: { p: any }) {
  const { toast } = useApp();
  const [added, setAdded] = useState(false);
  return (
    <div className="item top">
      <div className="grow">
        <Tokens tokens={p.tokens} size="s" />
        <div className="small muted">{p.en}{p.why ? ` — ${p.why}` : ""}</div>
      </div>
      <Speak text={p.zh} />
      <button className="btn sm" disabled={added} onClick={async () => { await api.post("/srs/sentence", { zh: p.zh, en: p.en }); setAdded(true); toast("Added to review"); }}>
        {added ? "Added" : <>{Icon.plus} Review</>}
      </button>
    </div>
  );
}
