// Writing with AI correction, and the weekly checkpoint quiz.
import { useState } from "react";
import { api } from "../api";
import { Tokens } from "../han";
import { ZhuyinInput } from "../ime";
import { Bar, Mcq, Speak } from "../ui";
import { HanziWrite } from "../writer";

const HAN = /[㐀-鿿]/g;

export function WritingFeedback({ fb, original }: { fb: any; original: string }) {
  return (
    <div className="col gap24">
      {fb.score != null && (
        <div className="row gap24 base">
          <div className="stat"><div className="v">{fb.score}<small>/ 5</small></div><div className="l">Naturalness</div></div>
          <p className="prose grow">{fb.comment}</p>
        </div>
      )}
      <div className="grid2">
        <div>
          <div className="label mb8">You wrote</div>
          <div className="han-text s ruby-none muted">{original}</div>
        </div>
        <div>
          <div className="label mb8">Corrected</div>
          <div className="han-text s ruby-none">{fb.corrected || original}</div>
        </div>
      </div>
      {fb.natural && (
        <div className="panel">
          <div className="row between"><span className="label">How a Taiwanese writer would put it</span><Speak text={fb.natural} /></div>
          {fb.natural_tokens?.length ? <Tokens tokens={fb.natural_tokens} size="s" className="mt8" /> : <div className="han-text s mt8">{fb.natural}</div>}
        </div>
      )}
      {fb.issues?.length > 0 && (
        <table className="t">
          <thead><tr><th>You wrote</th><th>Better</th><th>Why</th></tr></thead>
          <tbody>
            {fb.issues.map((it: any, i: number) => (
              <tr key={i}>
                <td className="zh strike" style={{ fontSize: 18 }}>{it.said}</td>
                <td className="zh" style={{ fontSize: 18 }}>{it.better}</td>
                <td className="small muted">{it.why}<div className="tiny faint upper mt4">{it.type}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function Writing({ payload, onDone }: { payload: any; onDone: (d?: any) => void }) {
  const [val, setVal] = useState("");
  const [fb, setFb] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const n = (val.match(HAN) || []).length;
  const min = payload.min_chars || 20;
  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      setFb(await api.post("/writing/feedback", { text: val, prompt: payload.prompt_zh, must_use: payload.must_use || [] }));
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy(false);
  };
  if (fb)
    return (
      <div className="col gap32">
        <div className="eyebrow">Feedback</div>
        <WritingFeedback fb={fb} original={val} />
        <div className="row end gap12">
          <button className="btn" onClick={() => setFb(null)}>Revise</button>
          <button className="btn primary lg" onClick={() => onDone({ score: fb.score, chars: n, text: val })}>Done</button>
        </div>
      </div>
    );
  return (
    <div className="col gap24">
      <div>
        <div className="eyebrow">Writing</div>
        <div className="han mt8" style={{ fontSize: 26, lineHeight: 1.6 }}>{payload.prompt_zh}</div>
        <div className="muted mt4">{payload.prompt_en}</div>
      </div>
      {payload.must_use?.length > 0 && (
        <div className="row wrap gap8">
          <span className="label">Try to use</span>
          {payload.must_use.map((w: string) => (
            <span key={w} className={`chip zh ${val.includes(w) ? "solid" : ""}`}>{w}</span>
          ))}
        </div>
      )}
      <ZhuyinInput value={val} onChange={setVal} rows={6} autoFocus placeholder="Write in Traditional characters with the zhuyin keyboard…" />
      {err && <div className="error">{err}</div>}
      <div className="row between">
        <span className="small muted num">{n} / {min} characters</span>
        <div className="row gap12">
          <button className="btn ghost sm" onClick={() => onDone({ skipped: true })}>Skip</button>
          <button className="btn primary" onClick={submit} disabled={busy || n < Math.min(min, 8)}>{busy ? "Reading…" : "Get feedback"}</button>
        </div>
      </div>
    </div>
  );
}

export function Checkpoint({ payload, onDone }: { payload: any; onDone: (d?: any) => void }) {
  const items: any[] = payload.items || [];
  const [i, setI] = useState(0);
  const [right, setRight] = useState(0);
  const [written, setWritten] = useState<number | null>(null);
  const it = items[i];
  const next = (ok: boolean) => {
    const r = right + (ok ? 1 : 0);
    setRight(r);
    setWritten(null);
    if (i + 1 >= items.length) setI(items.length);
    else setI(i + 1);
  };
  if (i >= items.length) {
    const score = items.length ? right / items.length : 1;
    return (
      <div className="col gap24 center" style={{ alignItems: "center", padding: "40px 0" }}>
        <div className="eyebrow">Weekly checkpoint</div>
        <div className="big-num">{Math.round(score * 100)}<span style={{ fontSize: 22 }}>%</span></div>
        <div className="muted">{right} of {items.length} correct</div>
        {payload.milestone && <p className="prose small muted panel" style={{ textAlign: "left" }}><span className="label">Milestone to aim for</span><br />{payload.milestone}</p>}
        <button className="btn primary lg" onClick={() => onDone({ score })}>Continue</button>
      </div>
    );
  }
  return (
    <div className="col gap24">
      <div className="row between"><span className="label">Weekly checkpoint</span><span className="tiny muted num">{i + 1} / {items.length}</span></div>
      <Bar value={i / items.length} />
      {it.kind === "write" ? (
        <div className="col gap16">
          <div className="label">Write the Traditional character</div>
          <div className="row gap32 wrap top">
            <HanziWrite char={it.char} mode="quiz" size={220} onComplete={(m) => setWritten(m)} key={i} />
            <div className="col gap8">
              <div className="pair"><span className="s">{it.simp}</span><span className="a">→</span><span className="t" style={{ fontSize: 44 }}>{written != null ? it.char : "？"}</span></div>
              <div className="muted">{it.pinyin} · {(it.en || "").split(";")[0]}</div>
              {it.word && it.word.length > 1 && <div className="han muted" style={{ fontSize: 22 }}>{written != null ? it.word : it.word.split(it.char).join("＿")}</div>}
              {written != null && <div className="small muted">{written === 0 ? "No mistakes." : `${written} stroke mistakes.`}</div>}
              <div className="row gap8 mt8">
                {written == null ? (
                  <button className="btn sm" onClick={() => next(false)}>I don't know</button>
                ) : (
                  <button className="btn primary" onClick={() => next(written <= 2)}>Next</button>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="col gap16">
          <div className="label">{it.sub}</div>
          <div className="han center" style={{ fontSize: 56, fontWeight: 700, padding: "8px 0" }}>{it.prompt}</div>
          <Mcq item={it} zhOptions={/[㄀-ㄯ㐀-鿿]/.test(it.options[0])} onAnswer={next} key={i} />
        </div>
      )}
    </div>
  );
}
