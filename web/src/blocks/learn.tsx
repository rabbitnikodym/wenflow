// Presentation blocks: Traditional characters, new vocabulary, grammar, Taiwan pronunciation.
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Reading, Tokens } from "../han";
import { ZhuyinInput } from "../ime";
import { ShadowLine } from "../speech";
import { useApp } from "../store";
import { Bar, Mcq, Speak, isTyping, say, useKey } from "../ui";
import { WritePractice } from "../writer";

const DECK: Record<string, string> = { tw: "台灣用語", hsk6: "HSK 6", book: "那些年" };

// ---------------------------------------------------------------------------------------------
// Simplified -> Traditional bridge unit
// ---------------------------------------------------------------------------------------------

export function Chars({ payload, onDone }: { payload: any; onDone: (d?: any) => void }) {
  const [step, setStep] = useState<"learn" | "write">("learn");
  const [wi, setWi] = useState(0);
  const [mist, setMist] = useState<number[]>([]);
  const [recall, setRecall] = useState<any[] | null>(null);

  useEffect(() => {
    if (payload.recall) api.get("/vocab/cards?kind=char&limit=200").then((r) => setRecall(r.cards.sort(() => Math.random() - 0.5).slice(0, 5).map((c: any) => c.data)));
  }, [payload.recall]);

  const cards: any[] = payload.recall ? recall || [] : payload.cards || [];
  const toWrite = useMemo(() => cards.slice(0, 6), [cards]);

  if (payload.recall && !recall) return <div className="muted">Loading…</div>;
  if (!cards.length) return <div className="col gap16"><div className="muted">No characters to practise yet.</div><button className="btn primary" onClick={() => onDone()}>Continue</button></div>;

  if (step === "write") {
    const c = toWrite[wi];
    const next = () => (wi + 1 >= toWrite.length ? onDone({ written: toWrite.length, mistakes: mist.reduce((a, b) => a + b, 0) }) : setWi(wi + 1));
    return (
      <div className="col gap24">
        <div className="row between">
          <span className="label">Write it from memory</span>
          <span className="tiny muted num">{wi + 1} / {toWrite.length}</span>
        </div>
        <Bar value={wi / toWrite.length} />
        <WritePractice
          char={c.t}
          onDone={(m) => setMist((x) => [...x, m])}
          hint={
            <div className="col gap8">
              <div className="pair"><span className="s">{c.s}</span><span className="a">→</span><span className="t" style={{ fontSize: 44 }}>？</span></div>
              <div className="muted">{c.pinyin} · {(c.en || "").split(";")[0]}</div>
              <div className="han muted" style={{ fontSize: 20 }}>{(c.word_info || []).map((w: any) => w.simp).join("　")}</div>
            </div>
          }
        />
        <div className="row end gap12">
          <button className="btn ghost sm" onClick={() => onDone({ written: wi })}>Finish</button>
          <button className="btn primary" onClick={next}>{wi + 1 >= toWrite.length ? "Done" : "Next character"}</button>
        </div>
      </div>
    );
  }

  return (
    <div className="col gap32">
      {!payload.recall && (
        <div className="row between base">
          <div>
            <div className="eyebrow">簡 → 繁</div>
            <h1 className="h1 mt8">Traditional characters</h1>
          </div>
          <span className="tiny muted upper">Unit {payload.n} / {payload.total}</span>
        </div>
      )}
      {payload.family && (
        <div className="panel col gap16">
          <div className="label">Component family</div>
          <div className="pair"><span className="s">{payload.family.simplified}</span><span className="a">→</span><span className="t">{payload.family.traditional}</span></div>
          <p className="prose muted">{payload.family.note}</p>
          <div className="row wrap gap24">
            {payload.family.examples.map((e: any) => (
              <div key={e.t} className="col gap4" style={{ cursor: "pointer" }} onClick={() => say(e.t)}>
                <div className="han" style={{ fontSize: 34, lineHeight: 1.2 }}>{e.t}</div>
                <div className="han faint" style={{ fontSize: 16 }}>{e.s}</div>
                <div className="tiny muted">{e.pinyin}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {payload.split && (
        <div className="panel col gap16">
          <div className="label">One Simplified character, several Traditional ones</div>
          <div className="row gap24 wrap top">
            <div className="han muted" style={{ fontSize: 64, fontWeight: 300, lineHeight: 1 }}>{payload.split.s}</div>
            <div className="col gap16 grow">
              {payload.split.options.map((o: any) => (
                <div key={o.t} className="row gap16 top">
                  <div className="han" style={{ fontSize: 44, fontWeight: 700, lineHeight: 1.1 }}>{o.t}</div>
                  <div>
                    <div className="small">{o.meaning}</div>
                    <div className="han muted" style={{ fontSize: 19 }}>{o.words.map((w: any) => w.trad).join("　")}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          {payload.split.tip && <p className="prose muted small">{payload.split.tip}</p>}
        </div>
      )}
      <div>
        <div className="label mb16">{payload.recall ? "Characters to write" : "Today's characters"}</div>
        <div className="list">
          {cards.map((c: any) => (
            <div key={c.t} className="item">
              <div className="pair" style={{ width: 170 }}>
                <span className="s" style={{ fontSize: 28 }}>{c.s}</span>
                <span className="a" style={{ fontSize: 13 }}>→</span>
                <span className="t" style={{ fontSize: 40 }}>{c.t}</span>
              </div>
              <div className="grow">
                <div className="row gap12 wrap"><Reading zhuyin={c.zhuyin} pinyin={c.pinyin} /></div>
                <div className="han muted" style={{ fontSize: 18 }}>{(c.words || []).join("　")}</div>
                {c.tip && <div className="tiny faint">{c.tip}</div>}
              </div>
              <Speak text={(c.words || [c.t])[0]} />
            </div>
          ))}
        </div>
      </div>
      <div className="row end gap12">
        <button className="btn" onClick={() => onDone({ written: 0 })}>Skip writing</button>
        <button className="btn primary lg" onClick={() => setStep("write")}>Practise writing</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// New words
// ---------------------------------------------------------------------------------------------

export function Vocab({ payload, onDone }: { payload: any; onDone: (d?: any) => void }) {
  const { settings } = useApp();
  const words: any[] = payload.words || [];
  const [i, setI] = useState(0);
  const [quiz, setQuiz] = useState(false);
  const [qi, setQi] = useState(0);
  const [right, setRight] = useState(0);
  const w = words[i];
  useEffect(() => {
    if (w && !quiz) say(w.trad);
  }, [w, quiz]);
  const questions = useMemo(
    () =>
      words
        .filter((x) => x.en)
        .map((x) => {
          const others = words.filter((y) => y.trad !== x.trad && y.en).map((y) => y.trad);
          const opts = [x.trad, ...others.sort(() => Math.random() - 0.5).slice(0, 3)].sort(() => Math.random() - 0.5);
          return { prompt: x.en, options: opts, answer: opts.indexOf(x.trad), say: x.trad };
        })
        .sort(() => Math.random() - 0.5),
    [words],
  );
  useKey((e) => {
    if (isTyping(e) || quiz) return;
    if (e.code === "ArrowRight" || e.code === "Space" || e.code === "Enter") {
      e.preventDefault();
      i + 1 >= words.length ? (questions.length >= 2 ? setQuiz(true) : onDone({})) : setI(i + 1);
    } else if (e.code === "ArrowLeft" && i > 0) setI(i - 1);
  });
  if (!words.length) return <div className="col gap16"><div className="muted">No new words today.</div><button className="btn primary" onClick={() => onDone()}>Continue</button></div>;

  if (quiz) {
    const q = questions[qi];
    return (
      <div className="col gap24">
        <div className="row between"><span className="label">Quick check</span><span className="tiny muted num">{qi + 1} / {questions.length}</span></div>
        <Bar value={qi / questions.length} />
        <div className="center" style={{ fontSize: 24, padding: "24px 0" }}>{q.prompt}</div>
        <Mcq item={q} zhOptions big onAnswer={(ok) => {
          const r = right + (ok ? 1 : 0);
          setRight(r);
          qi + 1 >= questions.length ? onDone({ score: r / questions.length }) : setQi(qi + 1);
        }} />
      </div>
    );
  }
  const long = w.trad.length > 4;
  return (
    <div className="col gap24">
      <div className="row between"><span className="label">New words</span><span className="tiny muted num">{i + 1} / {words.length}</span></div>
      <Bar value={i / words.length} />
      <div className="flash" style={{ minHeight: 420 }}>
        <div className="row gap8">
          <span className="chip zh solid">{DECK[w.deck] || w.deck}</span>
          {w.register && w.register !== "neutral" && <span className="chip">{w.register}</span>}
          {w.category && w.category !== "cedict" && <span className="chip">{w.category}</span>}
        </div>
        <div className={`word ${long ? "long" : ""}`}>{w.trad}</div>
        <div className="reading row gap8" style={{ justifyContent: "center" }}>
          <Reading zhuyin={w.zhuyin} pinyin={w.pinyin} />
          <Speak text={w.trad} />
        </div>
        <div className="meaning">{w.en}</div>
        <div className="row gap8 wrap" style={{ justifyContent: "center" }}>
          {settings.show_simplified && w.simp && <span className="chip zh">简 {w.simp}</span>}
          {w.mainland && <span className="chip zh">大陸 {w.mainland}</span>}
          {w.mainland_pinyin && <span className="chip">mainland: {w.mainland_pinyin}</span>}
        </div>
        {w.example?.zh && (
          <div style={{ maxWidth: 640 }}>
            <div className="row gap8" style={{ justifyContent: "center" }}>
              {w.example.tokens ? <Tokens tokens={w.example.tokens} size="s" /> : <span className="han-text s">{w.example.zh}</span>}
              <Speak text={w.example.zh} />
            </div>
            <div className="small muted">{w.example.en}</div>
          </div>
        )}
        {w.note && <div className="small muted" style={{ maxWidth: 580 }}>{w.note}</div>}
      </div>
      <div className="row between">
        <button className="btn ghost" onClick={() => setI(Math.max(0, i - 1))} disabled={i === 0}>← Back</button>
        <button className="btn primary" onClick={() => (i + 1 >= words.length ? (questions.length >= 2 ? setQuiz(true) : onDone({})) : setI(i + 1))}>
          {i + 1 >= words.length ? "Quick check" : "Next"} <span className="k">Space</span>
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Grammar point
// ---------------------------------------------------------------------------------------------

export function Grammar({ payload, onDone }: { payload: any; onDone: (d?: any) => void }) {
  const g = payload.point;
  const practice: any[] = g.practice || [];
  const [pi, setPi] = useState(-1);
  const [val, setVal] = useState("");
  const [shown, setShown] = useState(false);
  if (pi >= 0 && practice[pi]) {
    const p = practice[pi];
    const next = () => {
      setVal("");
      setShown(false);
      pi + 1 >= practice.length ? onDone({}) : setPi(pi + 1);
    };
    return (
      <div className="col gap24">
        <div className="row between"><span className="label">Use it — {g.pattern}</span><span className="tiny muted num">{pi + 1} / {practice.length}</span></div>
        <div style={{ fontSize: 22 }}>{p.en}</div>
        <ZhuyinInput value={val} onChange={setVal} rows={2} autoFocus onEnter={() => setShown(true)} key={pi} placeholder="Say it in Taiwanese Mandarin…" />
        {shown ? (
          <div className="col gap12">
            <div className="label">A natural answer</div>
            <div className="row gap8"><div className="han-text l">{p.zh}</div><Speak text={p.zh} /></div>
            <div className="row end"><button className="btn primary" onClick={next}>{pi + 1 >= practice.length ? "Done" : "Next"}</button></div>
          </div>
        ) : (
          <div className="row end"><button className="btn primary" onClick={() => setShown(true)}>Compare</button></div>
        )}
      </div>
    );
  }
  return (
    <div className="col gap32">
      <div>
        <div className="row gap8">
          <span className="eyebrow">Grammar</span>
          {g.category && <span className="chip">{g.category}</span>}
        </div>
        <h1 className="h1 mt8" style={{ textTransform: "none", letterSpacing: 0 }}>{g.title || g.pattern}</h1>
        {g.title && g.pattern && <div className="han mt8" style={{ fontSize: 24 }}>{g.pattern}</div>}
        {g.meaning && <div className="muted mt4">{g.meaning}</div>}
      </div>
      <p className="prose" style={{ fontSize: 16 }}>{g.explanation}</p>
      {(g.contrast || g.taiwan_note) && (
        <div className="panel">
          <div className="label mb8">{g.contrast ? "Compared with mainland / textbook usage" : "In Taiwan"}</div>
          <p className="prose muted zh-ui">{g.contrast || g.taiwan_note}</p>
        </div>
      )}
      <div className="list">
        {(g.examples || []).map((ex: any, k: number) => (
          <div key={k} className="item top">
            <div className="grow">
              {ex.tokens ? <Tokens tokens={ex.tokens} size="s" /> : <div className="han-text s">{ex.zh}</div>}
              <div className="small muted">{ex.en}</div>
            </div>
            <Speak text={ex.zh} />
          </div>
        ))}
      </div>
      <div className="row end">
        <button className="btn primary lg" onClick={() => (practice.length ? setPi(0) : onDone({}))}>{practice.length ? "Try it" : "Done"}</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Taiwan pronunciation
// ---------------------------------------------------------------------------------------------

const STATUS_NOTE: Record<string, string> = {
  "dictionary-only": "Dictionary standard in Taiwan; in everyday speech many people use the mainland-style reading.",
  "spoken-only": "Everyday spoken reading in Taiwan.",
};

export function Pron({ payload, onDone }: { payload: any; onDone: (d?: any) => void }) {
  const items: any[] = payload.items || [];
  const [i, setI] = useState(0);
  const it = items[i];
  useEffect(() => {
    if (it) say(it.trad);
  }, [it]);
  if (!it) return null;
  return (
    <div className="col gap24">
      <div className="row between"><span className="label">Read the Taiwan way</span><span className="tiny muted num">{i + 1} / {items.length}</span></div>
      <Bar value={i / items.length} />
      <div className="panel col gap16">
        <div className="row gap24 wrap base">
          <div className="han" style={{ fontSize: 64, fontWeight: 700, lineHeight: 1.1 }}>{it.trad}</div>
          <div className="muted">{it.en}</div>
        </div>
        <div className="row gap48 wrap">
          <div>
            <div className="label">Taiwan</div>
            <div className="row gap12 base" style={{ fontSize: 24 }}><span className="zy">{it.tw_zhuyin}</span><span>{it.tw}</span></div>
          </div>
          <div>
            <div className="label">Mainland</div>
            <div className="strike" style={{ fontSize: 24 }}>{it.cn || it.mainland || it.cn_word}</div>
          </div>
        </div>
        {it.note && <p className="prose muted small">{it.note}</p>}
        {STATUS_NOTE[it.status] && <p className="small faint">{STATUS_NOTE[it.status]}</p>}
      </div>
      <ShadowLine zh={it.example?.zh || it.trad} en={it.example?.en} tokens={it.example?.tokens} />
      <div className="row end">
        <button className="btn primary" onClick={() => (i + 1 >= items.length ? onDone({}) : setI(i + 1))}>{i + 1 >= items.length ? "Done" : "Next"}</button>
      </div>
    </div>
  );
}
