// Spaced-repetition review: words, Traditional characters (written by hand), Taiwan readings, sentences.
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Reading, Tokens } from "../han";
import { useApp } from "../store";
import { Bar, Loading, Speak, isTyping, say, useKey } from "../ui";
import { HanziWrite } from "../writer";

const DECK_LABEL: Record<string, string> = { tw: "台灣用語", hsk6: "HSK 6", book: "那些年", reading: "From reading", manual: "Added", tutor: "Conversation" };

export function Review({ limit = 40, kinds = "", onDone, embedded }: { limit?: number; kinds?: string; onDone?: (d: any) => void; embedded?: boolean }) {
  const { refresh } = useApp();
  const [queue, setQueue] = useState<any[] | null>(null);
  const [i, setI] = useState(0);
  const [shown, setShown] = useState(false);
  const [stats, setStats] = useState({ n: 0, ok: 0 });
  const [total, setTotal] = useState(0);
  const [handwrite, setHandwrite] = useState(true);
  const [mistakes, setMistakes] = useState<number | null>(null);

  useEffect(() => {
    api.get(`/srs/due?limit=${limit}${kinds ? `&kinds=${kinds}` : ""}`).then((r) => {
      setQueue(r.cards);
      setTotal(r.cards.length);
    });
  }, [limit, kinds]);

  const card = queue?.[i];
  useEffect(() => {
    setShown(false);
    setMistakes(null);
  }, [i]);

  const reveal = () => {
    if (!card || shown) return;
    setShown(true);
    const d = card.data;
    if (card.kind === "word") say(d.trad);
    if (card.kind === "pron") say(d.trad);
    if (card.kind === "sentence") say(d.zh);
  };

  const grade = async (g: number) => {
    if (!card) return;
    api.post("/srs/review", { id: card.id, grade: g, mode: card.kind }).catch(() => {});
    setStats((s) => ({ n: s.n + 1, ok: s.ok + (g > 1 ? 1 : 0) }));
    if (g === 1 && !card.again) setQueue((q) => [...(q || []), { ...card, again: true, new: false }]);
    setI((x) => x + 1);
  };

  useKey((e) => {
    if (isTyping(e) || !card) return;
    const isNew = card.new && card.kind !== "char";
    if (e.code === "Space" || e.code === "Enter") {
      e.preventDefault();
      if (isNew) grade(3);
      else if (!shown) reveal();
      else grade(3);
    } else if (shown && !isNew && ["1", "2", "3", "4"].includes(e.key)) grade(parseInt(e.key, 10));
  });

  const finished = queue != null && i >= queue.length;
  useEffect(() => {
    if (finished) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished]);

  if (!queue) return <Loading label="Collecting cards" />;
  if (finished)
    return (
      <div className="col gap24 center" style={{ alignItems: "center", padding: "60px 0" }}>
        <div className="eyebrow">{total ? "Review complete" : "Nothing due"}</div>
        {total ? (
          <>
            <div className="big-num">{stats.n}</div>
            <div className="muted">cards · {stats.n ? Math.round((stats.ok / stats.n) * 100) : 0}% recalled</div>
          </>
        ) : (
          <div className="muted prose">No cards are due right now. New words from today's lesson come up for review tomorrow.</div>
        )}
        {onDone && (
          <button className="btn primary lg" onClick={() => onDone({ reviewed: stats.n, correct: stats.ok })}>Continue</button>
        )}
      </div>
    );

  const d = card.data;
  const isNew = card.new && card.kind !== "char";
  return (
    <div className="col gap24">
      <div className="row gap16">
        <div className="grow"><Bar value={i / queue.length} /></div>
        <span className="tiny muted num">{i + 1} / {queue.length}</span>
      </div>
      <div className="flash">
        {card.kind === "word" && <WordFace d={d} shown={shown || isNew} isNew={isNew} reversed={!isNew && !!d.mainland && card.reps % 2 === 1} />}
        {card.kind === "char" && (
          <CharFace d={d} shown={shown} handwrite={handwrite} onWritten={(m) => { setMistakes(m); setShown(true); }} key={card.id + (card.again ? "a" : "")} />
        )}
        {card.kind === "pron" && <PronFace d={d} shown={shown || isNew} />}
        {card.kind === "sentence" && <SentenceFace d={d} shown={shown} />}
      </div>
      {isNew ? (
        <div className="row gap12 end">
          <button className="btn" onClick={() => grade(4)}>Already know it</button>
          <button className="btn primary" onClick={() => grade(3)}>Got it <span className="k">Space</span></button>
        </div>
      ) : !shown ? (
        <div className="row between">
          {card.kind === "char" ? (
            <button className="btn ghost sm" onClick={() => setHandwrite((h) => !h)}>{handwrite ? "Skip handwriting" : "Write by hand"}</button>
          ) : <span />}
          <button className="btn primary" onClick={reveal}>Show answer <span className="k">Space</span></button>
        </div>
      ) : (
        <div className="col gap8">
          {mistakes != null && (
            <div className="small muted center">
              {mistakes === 0 ? "Written without a mistake." : `${mistakes} stroke ${mistakes === 1 ? "mistake" : "mistakes"}.`} Suggested: {mistakes <= 1 ? "Good" : mistakes <= 4 ? "Hard" : "Again"}
            </div>
          )}
          <div className="grade">
            <button onClick={() => grade(1)}>Again<small>1 · soon</small></button>
            <button onClick={() => grade(2)}>Hard<small>2</small></button>
            <button onClick={() => grade(3)}>Good<small>3 · space</small></button>
            <button onClick={() => grade(4)}>Easy<small>4</small></button>
          </div>
        </div>
      )}
      {!embedded && <div className="tiny faint center">Space shows the answer · 1–4 grade it</div>}
    </div>
  );
}

function WordFace({ d, shown, isNew, reversed }: { d: any; shown: boolean; isNew: boolean; reversed: boolean }) {
  const { settings } = useApp();
  const long = (d.trad || "").length > 4;
  return (
    <>
      <div className="row gap8">
        {isNew && <span className="chip solid">New</span>}
        {d.deck && <span className="chip zh">{DECK_LABEL[d.deck] || d.deck}</span>}
        {d.register && d.register !== "neutral" && <span className="chip">{d.register}</span>}
      </div>
      {reversed && !shown ? (
        <>
          <div className="label mt16">In mainland Mandarin</div>
          <div className={`word ${long ? "long" : ""}`} style={{ color: "var(--muted)", fontWeight: 400 }}>{d.mainland}</div>
          <div className="meaning muted">{d.en}</div>
          <div className="label mt8">What do people say in Taiwan?</div>
        </>
      ) : (
        <div className={`word ${long ? "long" : ""}`}>{d.trad}</div>
      )}
      {shown && (
        <>
          <div className="reading row gap8" style={{ justifyContent: "center" }}>
            <Reading zhuyin={d.zhuyin} pinyin={d.pinyin} />
            <Speak text={d.trad} />
          </div>
          <div className="meaning">{d.en}</div>
          <div className="row gap8 wrap" style={{ justifyContent: "center" }}>
            {settings.show_simplified && d.simp && <span className="chip zh">简 {d.simp}</span>}
            {d.mainland && <span className="chip zh">大陸 {d.mainland}</span>}
            {d.mainland_pinyin && <span className="chip">mainland: {d.mainland_pinyin}</span>}
          </div>
          {d.example?.zh && (
            <div className="mt8" style={{ maxWidth: 620 }}>
              <div className="row gap8" style={{ justifyContent: "center" }}>
                {d.example.tokens ? <Tokens tokens={d.example.tokens} size="s" /> : <span className="han-text s">{d.example.zh}</span>}
                <Speak text={d.example.zh} />
              </div>
              {d.example.en && <div className="small muted">{d.example.en}</div>}
            </div>
          )}
          {d.note && <div className="small muted" style={{ maxWidth: 560 }}>{d.note}</div>}
        </>
      )}
    </>
  );
}

function CharFace({ d, shown, handwrite, onWritten }: { d: any; shown: boolean; handwrite: boolean; onWritten: (m: number) => void }) {
  const w = d.word_info?.[0];
  const ctx = useMemo(() => {
    const word: string = d.words?.[0] || d.t;
    return word.split("").map((c) => (c === d.t ? "＿" : c)).join("");
  }, [d]);
  return (
    <>
      <div className="label">Write the Traditional character</div>
      <div className="pair">
        <span className="s">{d.s}</span>
        <span className="a">→</span>
        {shown ? <span className="t">{d.t}</span> : <span className="t faint">？</span>}
      </div>
      <div className="row gap16 wrap" style={{ justifyContent: "center" }}>
        <span className="han" style={{ fontSize: 26 }}>{shown ? d.words?.[0] : ctx}</span>
        <span className="muted">{w?.pinyin || d.pinyin}</span>
        <span className="muted small">{(w?.en || d.en || "").split(";")[0]}</span>
      </div>
      {!shown && handwrite && <HanziWrite char={d.t} mode="quiz" size={200} onComplete={onWritten} />}
      {shown && (
        <>
          <HanziWrite char={d.t} mode="show" size={150} />
          {d.words?.length > 1 && <div className="han muted" style={{ fontSize: 20 }}>{d.words.join("　")}</div>}
          {d.tip && <div className="small muted" style={{ maxWidth: 520 }}>{d.tip}</div>}
        </>
      )}
    </>
  );
}

function PronFace({ d, shown }: { d: any; shown: boolean }) {
  return (
    <>
      <div className="label">How is it read in Taiwan?</div>
      <div className="word">{d.trad}</div>
      {d.en && <div className="muted">{d.en}</div>}
      {shown && (
        <>
          <div className="reading row gap8" style={{ justifyContent: "center" }}>
            <span className="zy">{d.tw_zhuyin}</span>
            <span>{d.tw}</span>
            <Speak text={d.trad} />
          </div>
          <div className="small">
            <span className="label">Mainland</span> <span className="strike">{d.cn || d.mainland || d.cn_word}</span>
          </div>
          {d.note && <div className="small muted" style={{ maxWidth: 560 }}>{d.note}</div>}
          {d.example?.zh && <div className="han muted" style={{ fontSize: 20 }}>{d.example.zh}</div>}
        </>
      )}
    </>
  );
}

function SentenceFace({ d, shown }: { d: any; shown: boolean }) {
  return (
    <>
      <div className="label">Say it in Taiwanese Mandarin</div>
      <div className="meaning" style={{ fontSize: 22 }}>{d.en}</div>
      {shown && (
        <div className="row gap8" style={{ justifyContent: "center" }}>
          {d.tokens ? <Tokens tokens={d.tokens} size="l" /> : <span className="han-text l">{d.zh}</span>}
          <Speak text={d.zh} />
        </div>
      )}
    </>
  );
}
