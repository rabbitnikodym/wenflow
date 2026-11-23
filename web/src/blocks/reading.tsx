// Reading view: annotated paragraphs, per-paragraph audio and translation, comprehension questions.
import { useState } from "react";
import { api } from "../api";
import { Reading, RubySwitch, Tok, Tokens } from "../han";
import { useApp } from "../store";
import { Icon, Mcq, Speak } from "../ui";

export function Paragraph({ tokens, size = "m", unknown }: { tokens: Tok[]; size?: "s" | "m" | "l"; unknown?: Set<string> }) {
  const [en, setEn] = useState("");
  const [busy, setBusy] = useState(false);
  const text = tokens.map((t) => t.w).join("");
  const translate = async () => {
    if (en) return setEn("");
    setBusy(true);
    try {
      setEn((await api.post("/translate", { text })).en);
    } catch (e: any) {
      setEn(`(${e.message})`);
    }
    setBusy(false);
  };
  return (
    <div className="para-wrap">
      <div className="row top gap8">
        <Tokens tokens={tokens} size={size} as="p" className="para grow" sentence="" unknown={unknown} />
        <div className="para-tools col gap4" style={{ paddingTop: 8 }}>
          <Speak text={text} />
          <button className={`icon-btn ${en ? "on" : ""}`} onClick={translate} title="Translate this paragraph">
            {busy ? <span className="spinner" style={{ width: 12, height: 12 }} /> : Icon.globe}
          </button>
        </div>
      </div>
      {en && <div className="trans">{en}</div>}
    </div>
  );
}

export function Questions({ questions, onDone }: { questions: any[]; onDone: (score: number) => void }) {
  const [i, setI] = useState(0);
  const [right, setRight] = useState(0);
  const q = questions[i];
  if (!q) return null;
  return (
    <div className="col gap16">
      <div className="row between"><span className="label">Comprehension</span><span className="tiny muted num">{i + 1} / {questions.length}</span></div>
      <div className="han" style={{ fontSize: 22, lineHeight: 1.7 }}>{q.q}</div>
      <Mcq item={q} zhOptions onAnswer={(ok) => {
        const r = right + (ok ? 1 : 0);
        setRight(r);
        i + 1 >= questions.length ? onDone(r / questions.length) : setI(i + 1);
      }} />
    </div>
  );
}

interface ReadingProps {
  payload: any; // {title, paragraphs, questions, source, url, prep, culture_note, no_book, book_title, clipped}
  onDone?: (d?: any) => void;
  kind?: string;
  doneLabel?: string;
}

export function ReadingBlock({ payload, onDone, kind = "reading", doneLabel = "Done" }: ReadingProps) {
  const { toast } = useApp();
  const [asking, setAsking] = useState(false);
  const paras: Tok[][] = payload.paragraphs || [];
  const qs: any[] = payload.questions || [];
  const chars = paras.reduce((n, p) => n + p.reduce((m, t) => m + (t.han ? t.w.length : 0), 0), 0);
  const finish = (score?: number) => onDone?.(score == null ? { chars } : { chars, score });
  const addAll = async () => {
    for (const w of payload.prep || []) await api.post("/srs/add", { word: w.trad, source: "book" }).catch(() => {});
    toast("Words added to review");
  };
  return (
    <div className="reader col gap24">
      {payload.no_book && (
        <div className="panel col gap12">
          <div className="label">那些年 · not imported yet</div>
          <p className="small muted prose">
            Import your copy of the novel in <a className="link" href="#/read">Read</a> and this slot becomes the next passage of the book.
            Until then you get an original school-life story that uses the novel's vocabulary.
          </p>
          {payload.culture_note && (
            <div className="mt8">
              <div className="h3">{payload.culture_note.title}</div>
              <p className="small muted prose mt4 zh-ui">{payload.culture_note.body}</p>
            </div>
          )}
        </div>
      )}
      <div>
        <div className="eyebrow">{payload.book_title || payload.source || (kind === "book" ? "Story" : "Reading")}</div>
        <h1 className="zh" style={{ fontSize: 34, fontWeight: 700, lineHeight: 1.4, marginTop: 8 }}>{payload.title}</h1>
        <div className="row gap16 mt8 tiny muted upper">
          <span className="num">{chars} characters</span>
          {payload.url && <a className="link" href={payload.url} target="_blank" rel="noreferrer">Original</a>}
          {payload.clipped && <span>Excerpt</span>}
        </div>
      </div>
      <div className="toolbar">
        <RubySwitch />
        <span className="tiny faint">Click any word for its meaning · hover a paragraph for audio and translation</span>
      </div>
      {payload.prep?.length > 0 && (
        <div className="panel flat col gap12">
          <div className="row between">
            <span className="label">Words to know in this passage</span>
            <button className="btn sm" onClick={addAll}>{Icon.plus} Add all to review</button>
          </div>
          <div className="row wrap gap24">
            {payload.prep.map((w: any) => (
              <div key={w.trad} className="col gap4" style={{ maxWidth: 190 }}>
                <div className="row gap8 base"><span className="han" style={{ fontSize: 24 }}>{w.trad}</span><span className="tiny"><Reading zhuyin={w.zhuyin} pinyin={w.pinyin} lean /></span></div>
                <div className="tiny muted">{(w.en || "").slice(0, 60)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      <div>
        {paras.map((p, i) => (
          <Paragraph key={i} tokens={p} />
        ))}
      </div>
      {asking && qs.length > 0 ? (
        <Questions questions={qs} onDone={(s) => finish(s)} />
      ) : (
        onDone && (
          <div className="row end gap12">
            {qs.length > 0 && <button className="btn" onClick={() => finish()}>Skip questions</button>}
            <button className="btn primary lg" onClick={() => (qs.length ? setAsking(true) : finish())}>{qs.length ? "Check understanding" : doneLabel}</button>
          </div>
        )
      )}
    </div>
  );
}
