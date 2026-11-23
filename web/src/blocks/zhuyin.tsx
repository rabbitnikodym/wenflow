// Zhuyin course units, key drills, typing drills and dictation.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { HanChar, Tok } from "../han";
import { Keyboard, ZhuyinInput, keyChar, useRawZhuyin } from "../ime";
import { useApp } from "../store";
import { Bar, Loading, Mcq, Speak, fmtTime, isTyping, say, saySymbol, useKey } from "../ui";

const HAN = /[㐀-鿿]/;
const hanOnly = (s: string) => Array.from(s).filter((c) => HAN.test(c)).join("");

// ---------------------------------------------------------------------------------------------
// Typing a known target
// ---------------------------------------------------------------------------------------------

export interface TypeItem {
  text: string;
  en?: string;
  zhuyin?: string;
  keys: string[];
  tokens?: Tok[];
}

export function TypingDrill({ items, onDone, title, timed }: { items: TypeItem[]; onDone: (d: any) => void; title?: string; timed?: boolean }) {
  const { settings } = useApp();
  const [i, setI] = useState(0);
  const [val, setVal] = useState("");
  const [showZy, setShowZy] = useState(true);
  const [showKb, setShowKb] = useState(true);
  const [ime, setIme] = useState({ pending: 0, partial: 0 });
  const [now, setNow] = useState(0);
  const t0 = useRef<number | null>(null);
  const stats = useRef({ chars: 0, errors: 0, typed: 0 });
  const prev = useRef("");
  const item = items[i];
  const target = useMemo(() => hanOnly(item?.text || ""), [item]);
  const typed = hanOnly(val);

  useEffect(() => {
    const id = window.setInterval(() => t0.current && setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, []);

  const finish = () => {
    const seconds = t0.current ? (Date.now() - t0.current) / 1000 : 0;
    const s = stats.current;
    const accuracy = s.typed ? Math.max(0, 1 - s.errors / s.typed) : 1;
    const cpm = seconds > 2 ? (s.chars / seconds) * 60 : 0;
    api.post("/typing/stat", { mode: timed ? "test" : "practice", chars: s.chars, seconds, accuracy }).catch(() => {});
    onDone({ chars: s.chars, seconds: Math.round(seconds), accuracy: Math.round(accuracy * 1000) / 1000, cpm: Math.round(cpm * 10) / 10 });
  };

  const advance = (count = true) => {
    if (count) stats.current.chars += target.length;
    prev.current = "";
    setVal("");
    if (i + 1 >= items.length) finish();
    else setI(i + 1);
  };

  const onChange = (v: string) => {
    if (!t0.current) t0.current = Date.now();
    const h = hanOnly(v);
    const before = prev.current;
    if (h.length > before.length) {
      for (let k = before.length; k < h.length; k++) {
        stats.current.typed++;
        if (h[k] !== target[k]) stats.current.errors++;
      }
    }
    prev.current = h;
    setVal(v);
    if (h === target) window.setTimeout(() => advance(), 280);
  };

  if (!item) return null;
  const idx = typed.length + ime.pending;
  const keysStr = item.keys[idx] || "";
  const next = keysStr ? [keysStr[Math.min(ime.partial, keysStr.length - 1)], ...keysStr.split("")] : [];
  const elapsed = t0.current ? ((now || Date.now()) - t0.current) / 1000 : 0;
  const liveCpm = elapsed > 3 ? Math.round(((stats.current.chars + typed.length) / elapsed) * 60) : 0;
  const wrong = typed.length >= target.length && typed !== target;

  let j = 0;
  return (
    <div className="col gap24">
      <div className="row between">
        <div className="row gap16">
          <span className="label">{title || "Type what you see"}</span>
          <span className="tiny muted num">{i + 1} / {items.length}</span>
        </div>
        <div className="row gap16">
          <span className="small muted num">{fmtTime(elapsed)}</span>
          <span className="small num">{liveCpm} <span className="muted">字/分</span></span>
        </div>
      </div>
      <Bar value={(i + typed.length / Math.max(1, target.length)) / items.length} />
      <div>
        <div className="target">
          {(item.tokens || [{ w: item.text, han: false }]).map((t, ti) =>
            !t.han ? (
              <span key={ti} className="punct">{t.w}</span>
            ) : (
              t.chars!.map((c, ci) => {
                const k = j++;
                const cls = k < typed.length ? (typed[k] === target[k] ? "ok" : "bad") : k === typed.length ? "cur" : "";
                return (
                  <span key={`${ti}-${ci}`} className={cls}>
                    <HanChar ch={showZy ? { ...c, zy: c.cz || c.zy } : c} ruby={showZy ? (settings.ruby === "pinyin" ? "pinyin" : "zhuyin") : "none"} />
                  </span>
                );
              })
            ),
          )}
        </div>
        {item.en && <div className="muted small mt8">{item.en}</div>}
      </div>
      <ZhuyinInput value={val} onChange={onChange} hint={item.text} expect={typed === target.slice(0, typed.length) ? target.slice(typed.length) : ""} rows={2} autoFocus onState={setIme} placeholder="Type here in zhuyin…" key={i} />
      {wrong && <div className="small" style={{ color: "var(--bad)" }}>Not quite — backspace to the underlined character, or press ↓ while composing to choose a different one.</div>}
      <div className="row between wrap gap16">
        <div className="row gap8">
          <button className={`btn sm ${showZy ? "on" : ""}`} onClick={() => setShowZy((x) => !x)}>Readings</button>
          <button className={`btn sm ${showKb ? "on" : ""}`} onClick={() => setShowKb((x) => !x)}>Keyboard</button>
          <Speak text={item.text} />
        </div>
        <button className="btn ghost sm" onClick={() => advance(false)}>Skip →</button>
      </div>
      {showKb && (
        <div className="center mt8">
          <Keyboard next={next} small />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Dictation: listen and type
// ---------------------------------------------------------------------------------------------

export function Dictation({ sentences, onDone }: { sentences: any[]; onDone: (d: any) => void }) {
  const [i, setI] = useState(0);
  const [val, setVal] = useState("");
  const [checked, setChecked] = useState(false);
  const [score, setScore] = useState({ ok: 0, n: 0 });
  const t0 = useRef(Date.now());
  const s = sentences[i];
  const target = hanOnly(s?.zh || "");
  const typed = hanOnly(val);

  useEffect(() => {
    if (s) say(s.zh);
  }, [s]);

  const check = () => {
    if (checked) return;
    let ok = 0;
    for (let k = 0; k < target.length; k++) if (typed[k] === target[k]) ok++;
    setScore((x) => ({ ok: x.ok + ok, n: x.n + target.length }));
    setChecked(true);
  };
  const next = () => {
    setChecked(false);
    setVal("");
    if (i + 1 >= sentences.length) {
      const seconds = (Date.now() - t0.current) / 1000;
      onDone({ accuracy: score.n ? score.ok / score.n : 0, chars: score.n, seconds: Math.round(seconds), cpm: seconds ? Math.round((score.n / seconds) * 600) / 10 : 0 });
    } else setI(i + 1);
  };
  useKey((e) => {
    if (checked && e.code === "Enter") {
      e.preventDefault();
      next();
    }
  });
  if (!s) return null;
  return (
    <div className="col gap24">
      <div className="row between">
        <span className="label">Listen and type what you hear</span>
        <span className="tiny muted num">{i + 1} / {sentences.length}</span>
      </div>
      <Bar value={i / sentences.length} />
      <div className="row gap12">
        <Speak text={s.zh} label="Play" />
        <Speak text={s.zh} slow label="Slow" />
      </div>
      {!checked ? (
        <>
          <ZhuyinInput value={val} onChange={setVal} hint={s.zh} expect={typed === target.slice(0, typed.length) ? target.slice(typed.length) : ""} rows={2} autoFocus onEnter={check} key={i} placeholder="Type the sentence in zhuyin, then press Enter…" />
          <div className="row end gap12">
            <button className="btn ghost sm" onClick={check}>Give up</button>
            <button className="btn primary" onClick={check} disabled={!typed.length}>Check</button>
          </div>
        </>
      ) : (
        <div className="col gap16">
          <div className="target">
            {Array.from(s.zh as string).map((c, k) => {
              if (!HAN.test(c)) return <span key={k} className="punct">{c}</span>;
              const pos = hanOnly((s.zh as string).slice(0, k)).length;
              return <span key={k} className={typed[pos] === c ? "" : "bad"}>{c}</span>;
            })}
          </div>
          <div className="small muted">You typed: <span className="zh" style={{ fontSize: 18 }}>{val || "—"}</span></div>
          {s.en && <div className="muted">{s.en}</div>}
          <div className="row end">
            <button className="btn primary" onClick={next}>Next <span className="k">Enter</span></button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Drills inside a zhuyin unit
// ---------------------------------------------------------------------------------------------

function McqDrill({ drill, onDone }: { drill: any; onDone: () => void }) {
  const [i, setI] = useState(0);
  const item = drill.items[i];
  if (!item) return null;
  const short = item.prompt.length <= 4;
  return (
    <div className="col gap24">
      <div className="row between">
        <span className="label">{drill.title}</span>
        <span className="tiny muted num">{i + 1} / {drill.items.length}</span>
      </div>
      <Bar value={i / drill.items.length} />
      <div className="center" style={{ padding: "12px 0" }}>
        {short ? <div className="bigsym">{item.prompt}</div> : <div className="zy" style={{ fontSize: 34, lineHeight: 1.6 }}>{item.prompt}</div>}
      </div>
      <Mcq item={item} big zhOptions={/[㄀-ㄯ㐀-鿿]/.test(item.options[0])} onAnswer={() => (i + 1 >= drill.items.length ? onDone() : setI(i + 1))} />
    </div>
  );
}

function KeyDrill({ drill, known, onDone }: { drill: any; known: string; onDone: () => void }) {
  const [i, setI] = useState(0);
  const [miss, setMiss] = useState(false);
  const [hit, setHit] = useState("");
  const item = drill.items[i];
  useEffect(() => {
    if (item && /[\u3105-\u3129]/.test(item.symbol)) saySymbol(item.symbol);
  }, [item]);
  useKey((e) => {
    if (isTyping(e) || e.ctrlKey || e.metaKey || e.altKey || !item) return;
    const ch = keyChar(e);
    if (ch === undefined) return;
    e.preventDefault();
    setHit(ch);
    window.setTimeout(() => setHit(""), 150);
    if (ch === item.key) {
      setMiss(false);
      if (i + 1 >= drill.items.length) onDone();
      else setI(i + 1);
    } else setMiss(true);
  });
  if (!item) return null;
  const hint = miss || i < 4;
  return (
    <div className="col gap24">
      <div className="row between">
        <span className="label">{drill.title} — press the key for this symbol</span>
        <span className="tiny muted num">{i + 1} / {drill.items.length}</span>
      </div>
      <Bar value={i / drill.items.length} />
      <div className="center">
        <div className="bigsym">{item.symbol === "ˉ" ? "ˉ" : item.symbol}</div>
        <div className="muted small">{item.symbol === "ˉ" ? "first tone (no mark)" : miss ? "Look at the highlighted key" : " "}</div>
      </div>
      <div className="center">
        <Keyboard next={hint ? [item.key] : []} known={known} hit={hit} />
      </div>
    </div>
  );
}

function SpellDrill({ drill, known, onDone }: { drill: any; known: string; onDone: () => void }) {
  const [i, setI] = useState(0);
  const [pos, setPos] = useState(0);
  const [done, setDone] = useState<string[]>([]);
  const [misses, setMisses] = useState(0);
  const [flash, setFlash] = useState("");
  const item = drill.items[i];
  const syls: string[] = item ? item.zhuyin.split(" ") : [];
  useEffect(() => {
    if (item) say(item.text);
  }, [item]);
  const { partial, hit } = useRawZhuyin((shown) => {
    if (!item) return;
    if (shown === syls[pos]) {
      const nd = [...done, shown];
      setFlash("");
      if (pos + 1 >= syls.length) {
        setDone(nd);
        window.setTimeout(() => {
          setDone([]);
          setPos(0);
          setMisses(0);
          if (i + 1 >= drill.items.length) onDone();
          else setI(i + 1);
        }, 420);
      } else {
        setDone(nd);
        setPos(pos + 1);
      }
    } else {
      setMisses((m) => m + 1);
      setFlash(shown);
      window.setTimeout(() => setFlash(""), 900);
    }
  });
  if (!item) return null;
  const keysStr: string = item.keys[pos] || "";
  const next = misses > 0 && keysStr ? [keysStr[Math.min(partial.length, keysStr.length - 1)], ...keysStr.split("")] : [];
  return (
    <div className="col gap24">
      <div className="row between">
        <span className="label">{drill.title} — type the zhuyin, ending with the tone key</span>
        <span className="tiny muted num">{i + 1} / {drill.items.length}</span>
      </div>
      <Bar value={i / drill.items.length} />
      <div className="center col gap8" style={{ alignItems: "center" }}>
        <div className="row gap16" style={{ justifyContent: "center" }}>
          <span className="han" style={{ fontSize: 84, fontWeight: 700, lineHeight: 1.1 }}>{item.text}</span>
          <Speak text={item.text} />
        </div>
        <div className="muted">{item.pinyin} · {(item.en || "").split(";")[0]}</div>
        <div className="rawsyl">
          <span>{done.join(" ")} </span>
          {flash ? <span style={{ color: "var(--bad)" }}>{flash}</span> : partial ? <span>{partial}</span> : <span className="ghost">{misses >= 2 ? syls[pos] : "＿"}</span>}
        </div>
        {misses >= 1 && !flash && <div className="small muted">{misses >= 2 ? "The answer is shown — type it once." : "Not that one. The highlighted keys show the way."}</div>}
      </div>
      <div className="center">
        <Keyboard next={next} known={known} hit={hit} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// A whole unit: teaching notes, then its drills
// ---------------------------------------------------------------------------------------------

export function ZhuyinUnit({ unit, onDone }: { unit: number; onDone: (d?: any) => void }) {
  const [u, setU] = useState<any>(null);
  const [step, setStep] = useState(0);
  const [result, setResult] = useState<any>(null);
  useEffect(() => {
    setU(null);
    setStep(0);
    api.get(`/zhuyin/unit/${unit}`).then(setU);
  }, [unit]);
  if (!u) return <Loading label="Loading unit" />;
  const known = u.known.map((s: any) => s.sym).join("");
  const drills = u.drills as any[];
  const total = drills.length + 1;
  const next = (d?: any) => {
    if (d) setResult(d);
    if (step >= drills.length) {
      api.post(`/zhuyin/unit/${unit}/done`).catch(() => {});
      onDone(d || result || {});
    } else setStep(step + 1);
  };
  const drill = step > 0 ? drills[step - 1] : null;
  return (
    <div className="col gap32">
      <div className="row gap16">
        <span className="tiny muted upper">Unit {u.n} / {u.total}</span>
        <div className="grow"><Bar value={step / total} /></div>
        <span className="tiny muted upper">{step === 0 ? "Learn" : `Drill ${step} / ${drills.length}`}</span>
      </div>
      {step === 0 && (
        <div className="col gap32">
          <div>
            <div className="eyebrow">{u.title_zh}</div>
            <h1 className="h1 mt8">{u.title}</h1>
          </div>
          {u.symbols.length > 0 && (
            <div className="sym-grid">
              {u.symbols.map((s: any) => (
                <div key={s.sym} className="sym new" onClick={() => saySymbol(s.sym)} title={`Hear its name: ${s.name}`}>
                  <div className="g">{s.sym}</div>
                  <div className="p">{s.pinyin} · <i>{s.name}</i></div>
                  <div className="k">key {s.key}</div>
                </div>
              ))}
            </div>
          )}
          {u.symbols.length > 0 && (
            <div className="col gap6">
              <div className="tiny faint upper mb8">Tap a symbol to hear its name · tap a word to hear it in use</div>
              {u.symbols.map((s: any) => (
                <div key={s.sym} className="row gap12 small">
                  <span className="zy" style={{ fontSize: 20, width: 28, cursor: "pointer" }} onClick={() => saySymbol(s.sym)}>{s.sym}</span>
                  <span style={{ width: 150, cursor: "pointer", flex: "none" }} onClick={() => say(s.ex)}>
                    <span className="zh" style={{ fontSize: 17 }}>{s.ex}</span> <span className="muted tiny">{s.ex_py}</span>
                  </span>
                  <span className="muted">{s.hint}</span>
                </div>
              ))}
            </div>
          )}
          {u.compounds && (
            <table className="t">
              <thead><tr><th>Zhuyin</th><th>Pinyin</th><th>Example</th><th /></tr></thead>
              <tbody>
                {u.compounds.map((c: any) => (
                  <tr key={c.zy}>
                    <td className="zy" style={{ fontSize: 22 }}>{c.zy}</td>
                    <td>{c.pinyin}</td>
                    <td className="zh" style={{ fontSize: 18 }}>{c.ex}</td>
                    <td><div className="row gap4"><Speak text={c.sound} /><button className="btn ghost sm" style={{ height: 28, padding: "0 6px" }} onClick={() => say(c.ex.split(" ")[0])}>{c.ex.split(" ")[0]}</button></div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {u.sections.map((s: any, k: number) => (
            <div key={k} className="col gap8">
              <div className="h2">{s.h}</div>
              <p className="prose zh-ui" style={{ lineHeight: 1.8 }}>{s.body}</p>
            </div>
          ))}
          {u.symbols.length > 0 && (
            <div className="center">
              <Keyboard known={known} next={u.symbols.map((s: any) => s.key)} />
            </div>
          )}
          <div className="row end">
            <button className="btn primary lg" onClick={() => next()}>{drills.length ? "Start drills" : "Done"}</button>
          </div>
        </div>
      )}
      {drill?.type === "mcq" && <McqDrill key={step} drill={drill} onDone={() => next()} />}
      {drill?.type === "keys" && <KeyDrill key={step} drill={drill} known={known} onDone={() => next()} />}
      {drill?.type === "spell" && <SpellDrill key={step} drill={drill} known={known} onDone={() => next()} />}
      {drill?.type === "type" && <TypingDrill key={step} items={drill.items} title={drill.title} timed={drill.timed} onDone={(d) => next(d)} />}
    </div>
  );
}

/** Result line shown after a typing drill. */
export function TypingResult({ d }: { d: any }) {
  if (!d || d.cpm == null) return null;
  return (
    <div className="row gap48">
      <div className="stat"><div className="v">{Math.round(d.cpm)}<small>字/分</small></div><div className="l">Speed</div></div>
      <div className="stat"><div className="v">{Math.round((d.accuracy ?? 1) * 100)}<small>%</small></div><div className="l">Accuracy</div></div>
      <div className="stat"><div className="v">{d.chars}</div><div className="l">Characters</div></div>
    </div>
  );
}
