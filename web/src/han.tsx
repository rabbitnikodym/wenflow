// Chinese text with readings (zhuyin beside each character, or pinyin above) and a click-to-look-up popup.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Ruby, useApp } from "./store";
import { Icon, Speak, say } from "./ui";

export interface Ch {
  c: string;
  py: string;
  zy: string;
  t: number;
  cz?: string;
}
export interface Tok {
  w: string;
  han: boolean;
  chars?: Ch[];
  g?: string;
  hsk?: number | null;
  f?: number;
}

interface PopState {
  word: string;
  sentence: string;
  x: number;
  top?: number;
  bottom?: number;
}

const PopCtx = createContext<{ open: (word: string, el: HTMLElement, sentence?: string) => void; current: string }>({
  open: () => {},
  current: "",
});

export function PopupProvider({ children }: { children: any }) {
  const [pop, setPop] = useState<PopState | null>(null);
  const open = useCallback((word: string, el: HTMLElement, sentence = "") => {
    const r = el.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const x = Math.max(12, Math.min(r.left, vw - 380));
    setPop(r.top > vh * 0.55 ? { word, sentence, x, bottom: vh - r.top + 10 } : { word, sentence, x, top: r.bottom + 10 });
  }, []);
  useEffect(() => {
    if (!pop) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPop(null);
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest(".pop") && !t.closest(".tok")) setPop(null);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [pop]);
  return (
    <PopCtx.Provider value={{ open, current: pop?.word || "" }}>
      {children}
      {pop && <WordPopup key={pop.word + pop.x + (pop.top ?? pop.bottom)} pop={pop} close={() => setPop(null)} />}
    </PopCtx.Provider>
  );
}

function WordPopup({ pop, close }: { pop: PopState; close: () => void }) {
  const { settings, toast } = useApp();
  const [d, setD] = useState<any>(null);
  const [extra, setExtra] = useState<any>(null);
  const [moe, setMoe] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [added, setAdded] = useState(false);
  useEffect(() => {
    let live = true;
    api.get(`/dict?w=${encodeURIComponent(pop.word)}`).then((r) => live && setD(r)).catch(() => live && setD({ word: pop.word, info: { trad: pop.word }, entries: [] }));
    return () => {
      live = false;
    };
  }, [pop.word]);
  const info = d?.info || {};
  const add = async () => {
    await api.post("/srs/add", { word: pop.word, sentence: pop.sentence, source: "reading" });
    setAdded(true);
    toast("Added to review");
  };
  const known = async () => {
    await api.post("/words", { word: pop.word, status: "known" });
    toast("Marked as known");
    close();
  };
  const explain = async () => {
    setBusy("explain");
    try {
      setExtra(await api.post("/explain", { word: pop.word, sentence: pop.sentence }));
    } catch (e: any) {
      toast(e.message);
    }
    setBusy("");
  };
  const loadMoe = async () => {
    setBusy("moe");
    try {
      setMoe(await api.get(`/moedict?w=${encodeURIComponent(pop.word)}`));
    } catch {
      setMoe({ heteronyms: [] });
    }
    setBusy("");
  };
  return (
    <div className="pop" style={{ left: pop.x, top: pop.top, bottom: pop.bottom }}>
      <div className="row between top">
        <div className="w">{pop.word}</div>
        <div className="row gap4">
          <Speak text={pop.word} />
          <button className="icon-btn" onClick={close}>{Icon.x}</button>
        </div>
      </div>
      {!d ? (
        <div className="muted small mt12">…</div>
      ) : (
        <>
          <div className="r row wrap gap16">
            <span className="zy">{info.zhuyin}</span>
            <span className="muted">{info.pinyin}</span>
          </div>
          <div className="row wrap gap6 mt8">
            {settings.show_simplified && info.simp && <span className="chip zh">简 {info.simp}</span>}
            {info.hsk && <span className="chip">HSK {info.hsk}</span>}
            {info.tw && <span className="chip solid">台灣</span>}
            {info.register && info.register !== "neutral" && <span className="chip">{info.register}</span>}
            {(d.card || added) && <span className="chip">in review</span>}
            {d.status === "known" && <span className="chip">known</span>}
          </div>
          {info.mainland_pinyin && (
            <div className="small mt8">
              <span className="label">Mainland reading</span> <span className="strike">{info.mainland_pinyin}</span>
            </div>
          )}
          {d.pron && (
            <div className="small mt8 muted">{d.pron.note}</div>
          )}
          {d.entries?.length > 0 ? (
            <ul className="defs">
              {d.entries.slice(0, 3).map((e: any, i: number) => (
                <li key={i}>
                  {d.entries.length > 1 && <span className="muted">{e.pinyin} · </span>}
                  {e.defs.slice(0, 5).map(cleanDef).join("; ")}
                </li>
              ))}
            </ul>
          ) : (
            info.en && <div className="defs">{info.en}</div>
          )}
          {d.tw && (
            <>
              <div className="sep" />
              {d.tw.mainland && (
                <div className="small">
                  <span className="label">Mainland says</span> <span className="zh" style={{ fontSize: 16 }}>{d.tw.mainland}</span>
                </div>
              )}
              {d.tw.note && <div className="small muted mt4">{d.tw.note}</div>}
              {d.tw.example?.zh && (
                <div className="mt8">
                  <span className="zh" style={{ fontSize: 16 }}>{d.tw.example.zh}</span>
                  <div className="small muted">{d.tw.example.en}</div>
                </div>
              )}
            </>
          )}
          {d.chars?.length > 1 && (
            <>
              <div className="sep" />
              <div className="col gap4">
                {d.chars.map((c: any, i: number) => (
                  <div key={i} className="row gap8 small top">
                    <span className="zh" style={{ fontSize: 18, lineHeight: 1.2 }}>{c.c}</span>
                    {settings.show_simplified && c.simp && <span className="faint zh">{c.simp}</span>}
                    <span className="zy muted">{c.zhuyin}</span>
                    <span className="muted grow" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.en}</span>
                  </div>
                ))}
              </div>
            </>
          )}
          {extra && (
            <>
              <div className="sep" />
              <div className="small">{extra.meaning}</div>
              {extra.nuance && <div className="small muted mt4">{extra.nuance}</div>}
              {(extra.examples || []).map((ex: any, i: number) => (
                <div key={i} className="mt8">
                  <div className="row gap6">
                    <span className="zh" style={{ fontSize: 16 }}>{ex.zh}</span>
                    <Speak text={ex.zh} />
                  </div>
                  <div className="small muted">{ex.en}</div>
                </div>
              ))}
              {extra.similar?.length > 0 && <div className="small muted mt8 zh">≈ {extra.similar.join("、")}</div>}
            </>
          )}
          {moe && (
            <>
              <div className="sep" />
              <div className="label">教育部國語辭典</div>
              {moe.heteronyms?.length ? (
                moe.heteronyms.map((h: any, i: number) => (
                  <div key={i} className="mt8">
                    <div className="zy small muted">{h.bopomofo}</div>
                    <ol style={{ margin: "4px 0 0", paddingLeft: 18 }} className="zh small">
                      {h.defs.map((x: any, j: number) => (
                        <li key={j}>{x.type ? `〔${x.type}〕` : ""}{x.def}</li>
                      ))}
                    </ol>
                  </div>
                ))
              ) : (
                <div className="small muted mt4">No entry.</div>
              )}
            </>
          )}
          <div className="sep" />
          <div className="row wrap gap8">
            {!d.card && !added && (
              <button className="btn sm primary" onClick={add}>
                {Icon.plus} Review
              </button>
            )}
            {d.status !== "known" && (
              <button className="btn sm" onClick={known}>Known</button>
            )}
            {!extra && (
              <button className="btn sm" onClick={explain} disabled={busy === "explain"}>
                {busy === "explain" ? "…" : "Explain"}
              </button>
            )}
            {!moe && (
              <button className="btn sm" onClick={loadMoe} disabled={busy === "moe"}>
                <span className="zh" style={{ letterSpacing: ".1em" }}>國語辭典</span>
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function cleanDef(d: string) {
  return d.replace(/([㐀-鿿]+)\|[㐀-鿿]+/g, "$1").replace(/\[[^\]]*\]/g, "");
}

/**
 * The zhuyin symbols taught so far, while the zhuyin course is still running; null once every symbol
 * is known (or the learner switched the help off). Until then a syllable that uses a symbol not yet
 * taught keeps its pinyin, so no part of a lesson depends on zhuyin that has not been covered.
 */
export function useKnownZhuyin(): string | null {
  const { state, settings } = useApp();
  const z = state?.zhuyin;
  if (!z || z.all_symbols || !settings.pinyin_support) return null;
  return z.known;
}

/** Does this zhuyin spelling use a symbol the learner has not been taught yet? */
export function beyond(zhuyin: string | undefined, known: string | null): boolean {
  if (known == null || !zhuyin) return false;
  for (const s of zhuyin) if (!" ˊˇˋ˙".includes(s) && !known.includes(s)) return true;
  return false;
}

export function HanChar({ ch, ruby, known = null }: { ch: Ch; ruby: Ruby; known?: string | null }) {
  const tone = `tone${ch.t || 0}`;
  if (ruby === "none" || (!ch.zy && !ch.py)) return <span className={tone}>{ch.c}</span>;
  if (ruby === "pinyin")
    return (
      <span className={`pc ${tone}`}>
        <span>{ch.c}</span>
        <span className="p">{ch.py}</span>
      </span>
    );
  const zy = ch.zy;
  const neutral = zy.startsWith("˙");
  const mark = /[ˊˇˋ]$/.test(zy) ? zy.slice(-1) : "";
  const syms = zy.replace(/[ˊˇˋ˙]/g, "");
  return (
    <span className={`zc ${tone}`}>
      {ch.py && beyond(syms, known) && <span className="p">{ch.py}</span>}
      <span className="h">{ch.c}</span>
      <span className="z">
        {neutral && <span className="n">˙</span>}
        <span className="s">{syms}</span>
        {mark && <span className="m">{mark}</span>}
      </span>
    </span>
  );
}

interface TokensProps {
  tokens: Tok[];
  size?: "s" | "m" | "l" | "xl";
  ruby?: Ruby;
  plain?: boolean; // not clickable
  className?: string;
  sentence?: string;
  as?: "div" | "span" | "p";
  unknown?: Set<string>;
}

/** A run of annotated text. Words are clickable for the dictionary popup unless `plain`. */
export function Tokens({ tokens, size = "m", ruby, plain, className = "", sentence, as = "div", unknown }: TokensProps) {
  const { settings } = useApp();
  const { open, current } = useContext(PopCtx);
  const mode = ruby ?? settings.ruby;
  const known = useKnownZhuyin();
  const help = mode === "zhuyin" && known != null;
  const ctx = sentence ?? tokens.map((t) => t.w).join("");
  const Tag = as as any;
  const sz = size === "m" ? "" : size;
  return (
    <Tag className={`han-text ${sz} ruby-${mode} ${help ? "support" : ""} ${className}`}>
      {tokens.map((t, i) =>
        !t.han ? (
          <span key={i} className="punct">{t.w}</span>
        ) : (
          <span
            key={i}
            className={`tok ${plain ? "plain" : ""} ${current === t.w ? "sel" : ""} ${unknown?.has(t.w) ? "unk" : ""}`}
            onClick={plain ? undefined : (e) => open(t.w, e.currentTarget as HTMLElement, ctx.length <= 80 ? ctx : "")}
          >
            {t.chars!.map((c, j) => (
              <HanChar key={j} ch={c} ruby={mode} known={help ? known : null} />
            ))}
          </span>
        ),
      )}
    </Tag>
  );
}

const annoCache = new Map<string, Tok[][]>();

/** Annotate plain text on demand (cached). Returns paragraphs of tokens. */
export function useTokens(text: string | undefined | null, gloss = true): Tok[][] | null {
  const [val, setVal] = useState<Tok[][] | null>(text ? annoCache.get(text) || null : null);
  const ref = useRef(text);
  ref.current = text;
  useEffect(() => {
    if (!text) {
      setVal(null);
      return;
    }
    const hit = annoCache.get(text);
    if (hit) {
      setVal(hit);
      return;
    }
    setVal(null);
    api.post("/annotate", { text, gloss }).then((r) => {
      annoCache.set(text, r.paragraphs);
      if (ref.current === text) setVal(r.paragraphs);
    }).catch(() => {});
  }, [text, gloss]);
  return val;
}

/** Plain string rendered as annotated text (fetches readings). Falls back to the raw string while loading. */
export function Zh({ text, size, plain, className, ruby }: { text: string; size?: TokensProps["size"]; plain?: boolean; className?: string; ruby?: Ruby }) {
  const paras = useTokens(text);
  if (!paras) return <div className={`han-text ${size || ""} ${className || ""}`}>{text}</div>;
  return (
    <>
      {paras.map((p, i) => (
        <Tokens key={i} tokens={p} size={size} plain={plain} className={className} ruby={ruby} />
      ))}
    </>
  );
}

/** Zhuyin + pinyin line for a word: shows both. With `lean`, pinyin appears only while it is still needed. */
export function Reading({ zhuyin, pinyin, lean, className = "" }: { zhuyin?: string; pinyin?: string; lean?: boolean; className?: string }) {
  const { settings } = useApp();
  const known = useKnownZhuyin();
  if (lean && settings.ruby !== "pinyin" && !beyond(zhuyin, known)) pinyin = undefined;
  return (
    <span className={`row gap16 wrap ${className}`} style={{ justifyContent: "inherit" }}>
      {zhuyin && settings.ruby !== "pinyin" && <span className="zy">{zhuyin}</span>}
      {pinyin && <span className={settings.ruby === "pinyin" ? "" : "muted"}>{pinyin}</span>}
      {zhuyin && settings.ruby === "pinyin" && <span className="zy muted">{zhuyin}</span>}
    </span>
  );
}

/** Ruby mode switch shared by reader, player and lessons. */
export function RubySwitch() {
  const { settings, set } = useApp();
  return (
    <div className="seg">
      {(["zhuyin", "pinyin", "none"] as Ruby[]).map((m) => (
        <button key={m} className={settings.ruby === m ? "on" : ""} onClick={() => set({ ruby: m })}>
          {m === "zhuyin" ? <span className="zh">注音</span> : m === "pinyin" ? "Pīnyīn" : "Off"}
        </button>
      ))}
      <button className={settings.tone_colors ? "on" : ""} onClick={() => set({ tone_colors: !settings.tone_colors })} title="Colour characters by tone">
        Tones
      </button>
    </div>
  );
}

export { say };
