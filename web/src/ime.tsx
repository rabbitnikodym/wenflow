// A built-in zhuyin (注音) input method on the standard 大千 layout, plus the on-screen keyboard.
// It behaves like Microsoft 注音: symbols fill initial / medial / final slots, a tone key ends the
// syllable, the run is converted automatically, ↓ opens candidates, Enter commits.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "./api";
import { useApp } from "./store";

export const KEYMAP: Record<string, string> = {
  "1": "ㄅ", q: "ㄆ", a: "ㄇ", z: "ㄈ", "2": "ㄉ", w: "ㄊ", s: "ㄋ", x: "ㄌ", e: "ㄍ", d: "ㄎ", c: "ㄏ",
  r: "ㄐ", f: "ㄑ", v: "ㄒ", "5": "ㄓ", t: "ㄔ", g: "ㄕ", b: "ㄖ", y: "ㄗ", h: "ㄘ", n: "ㄙ",
  u: "ㄧ", j: "ㄨ", m: "ㄩ", "8": "ㄚ", i: "ㄛ", k: "ㄜ", ",": "ㄝ", "9": "ㄞ", o: "ㄟ", l: "ㄠ", ".": "ㄡ",
  "0": "ㄢ", p: "ㄣ", ";": "ㄤ", "/": "ㄥ", "-": "ㄦ",
};
export const TONEKEYS: Record<string, string> = { " ": "ˉ", "6": "ˊ", "3": "ˇ", "4": "ˋ", "7": "˙" };
export const TONE_LABEL: Record<string, string> = { "3": "ˇ", "4": "ˋ", "6": "ˊ", "7": "˙" };
export const ROWS = ["1234567890-", "qwertyuiop", "asdfghjkl;", "zxcvbnm,./"];
const MEDIALS = "ㄧㄨㄩ";
const FINALS = "ㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦ";

const CODE2CHAR: Record<string, string> = {
  Space: " ", Comma: ",", Period: ".", Slash: "/", Semicolon: ";", Minus: "-",
};
for (const d of "0123456789") CODE2CHAR[`Digit${d}`] = d;
for (const l of "abcdefghijklmnopqrstuvwxyz") CODE2CHAR[`Key${l.toUpperCase()}`] = l;

const SHIFT_PUNCT: Record<string, string> = {
  Comma: "，", Period: "。", Slash: "？", Digit1: "！", Semicolon: "：", Quote: "；", Digit9: "（", Digit0: "）", Minus: "——", Backquote: "～",
};
const DIRECT_PUNCT: Record<string, string> = { Quote: "、", BracketLeft: "「", BracketRight: "」", Backslash: "、" };

/** Physical key -> layout character, independent of the OS keyboard language. */
export const keyChar = (e: KeyboardEvent | React.KeyboardEvent) => CODE2CHAR[e.code];

interface Part {
  i: string;
  m: string;
  f: string;
}
const EMPTY: Part = { i: "", m: "", f: "" };
const partStr = (p: Part) => p.i + p.m + p.f;

function setSlot(p: Part, sym: string): Part {
  if (MEDIALS.includes(sym)) return { ...p, m: sym };
  if (FINALS.includes(sym)) return { ...p, f: sym };
  return { ...p, i: sym };
}

/** Zhuyin as written: tone 1 unmarked, neutral dot first. */
export function showSyllable(body: string, tone: string) {
  if (tone === "˙") return "˙" + body;
  return tone === "ˉ" ? body : body + tone;
}
const keyToShown = (k: string) => showSyllable(k.slice(0, -1), k.slice(-1));

interface ImeProps {
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  expect?: string; // the exact characters expected next (drills), one per syllable
  rows?: number;
  placeholder?: string;
  autoFocus?: boolean;
  onEnter?: () => void;
  onState?: (s: { pending: number; partial: number }) => void;
  className?: string;
  disabled?: boolean;
  style?: React.CSSProperties;
}

export function ZhuyinInput({ value, onChange, hint = "", expect = "", rows = 3, placeholder, autoFocus, onEnter, onState, className = "", disabled, style }: ImeProps) {
  const { settings, state } = useApp();
  const zy = state?.zhuyin;
  const early = !!zy && !zy.can_type; // the course has not reached whole-sentence typing yet
  const [imeOn, setImeOn] = useState(settings.builtin_ime);
  const [part, setPart] = useState<Part>(EMPTY);
  const [keys, setKeys] = useState<string[]>([]);
  const [conv, setConv] = useState<{ for: string; best: string; candidates: { word: string; n: number }[] } | null>(null);
  const [picker, setPicker] = useState(false);
  const [page, setPage] = useState(0);
  const ta = useRef<HTMLTextAreaElement>(null);
  const val = useRef(value);
  const caret = useRef<number | null>(null);
  const req = useRef(0);
  const expectRef = useRef(expect);
  expectRef.current = expect;
  val.current = value;

  useEffect(() => setImeOn(settings.builtin_ime), [settings.builtin_ime]);
  useEffect(() => {
    if (autoFocus) ta.current?.focus();
  }, [autoFocus]);
  useLayoutEffect(() => {
    if (caret.current != null && ta.current) {
      ta.current.setSelectionRange(caret.current, caret.current);
      caret.current = null;
    }
  }, [value]);
  useEffect(() => {
    onState?.({ pending: keys.length, partial: partStr(part).length });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keys.length, part]);

  const fetchConv = useCallback(
    async (ks: string[]) => {
      if (!ks.length) {
        setConv(null);
        return null;
      }
      const id = ++req.current;
      try {
        const r = await api.post("/ime", { keys: ks, hint, expect: expectRef.current });
        const c = { for: ks.join("|"), best: r.best, candidates: r.candidates };
        if (id === req.current) setConv(c);
        return c;
      } catch {
        return null;
      }
    },
    [hint],
  );

  const insert = (text: string) => {
    const el = ta.current;
    const v = val.current;
    const start = caret.current ?? el?.selectionStart ?? v.length;
    const end = caret.current ?? el?.selectionEnd ?? v.length;
    const nv = v.slice(0, start) + text + v.slice(end);
    val.current = nv;
    caret.current = start + text.length;
    onChange(nv);
  };

  const reset = () => {
    setKeys([]);
    setPart(EMPTY);
    setConv(null);
    setPicker(false);
    setPage(0);
    req.current++;
  };

  const commitBest = async () => {
    if (!keys.length) {
      reset();
      return;
    }
    const k = keys;
    const c = conv && conv.for === k.join("|") ? conv : await fetchConv(k);
    reset();
    insert(c?.best || k.map(keyToShown).join(""));
  };

  const pick = (c: { word: string; n: number }) => {
    insert(c.word);
    const rest = keys.slice(c.n);
    setKeys(rest);
    setPicker(false);
    setPage(0);
    fetchConv(rest);
    ta.current?.focus();
  };

  const punct = async (p: string) => {
    if (keys.length) await commitBest();
    else reset();
    insert(p);
  };

  const finalize = (tone: string) => {
    const k = partStr(part) + tone;
    const nk = [...keys, k];
    setKeys(nk);
    setPart(EMPTY);
    if (nk.length >= 24) {
      // very long run: commit what we have and carry on
      fetchConv(nk).then((c) => {
        reset();
        insert(c?.best || "");
      });
      return;
    }
    fetchConv(nk);
  };

  const cands = conv && conv.for === keys.join("|") ? conv.candidates : [];
  const pageCands = cands.slice(page * 9, page * 9 + 9);
  const pages = Math.max(1, Math.ceil(cands.length / 9));

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!imeOn) {
      if (e.key === "Enter" && onEnter && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault();
        onEnter();
      }
      return;
    }
    if (e.nativeEvent.isComposing || e.key === "Process") return;
    const hasPart = partStr(part).length > 0;
    const composing = keys.length > 0 || hasPart;
    const code = e.code;
    if (e.ctrlKey || e.metaKey || e.altKey) {
      if (e.ctrlKey && (code === "Comma" || code === "Period")) {
        e.preventDefault();
        punct(code === "Comma" ? "，" : "。");
      }
      return;
    }
    if (picker) {
      e.preventDefault();
      if (/^Digit[1-9]$/.test(code)) {
        const c = pageCands[parseInt(code.slice(5), 10) - 1];
        if (c) pick(c);
      } else if (["ArrowRight", "ArrowDown", "Space", "PageDown"].includes(code)) setPage((p) => (p + 1) % pages);
      else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(code)) setPage((p) => (p - 1 + pages) % pages);
      else if (code === "Enter") pageCands[0] && pick(pageCands[0]);
      else if (code === "Escape" || code === "Backspace") setPicker(false);
      return;
    }
    if (e.shiftKey) {
      const p = SHIFT_PUNCT[code];
      if (p) {
        e.preventDefault();
        punct(p);
      }
      return;
    }
    if (code === "Backspace") {
      if (hasPart) {
        e.preventDefault();
        setPart((p) => (p.f ? { ...p, f: "" } : p.m ? { ...p, m: "" } : { ...p, i: "" }));
      } else if (keys.length) {
        e.preventDefault();
        const nk = keys.slice(0, -1);
        setKeys(nk);
        fetchConv(nk);
      }
      return;
    }
    if (code === "Escape") {
      if (composing) {
        e.preventDefault();
        reset();
      }
      return;
    }
    if (code === "Enter") {
      if (composing) {
        e.preventDefault();
        commitBest();
      } else if (onEnter) {
        e.preventDefault();
        onEnter();
      }
      return;
    }
    if (code === "ArrowDown" || code === "Tab") {
      if (keys.length && !hasPart) {
        e.preventDefault();
        setPicker(true);
        setPage(0);
      }
      return;
    }
    const ch = CODE2CHAR[code];
    if (ch === undefined) {
      const dp = DIRECT_PUNCT[code];
      if (dp) {
        e.preventDefault();
        punct(dp);
      }
      return;
    }
    const tone = TONEKEYS[ch];
    if (tone) {
      if (hasPart) {
        e.preventDefault();
        finalize(tone);
      } else if (keys.length) {
        e.preventDefault();
        if (ch === " ") commitBest();
      }
      return; // nothing composing: space and digits type themselves
    }
    const sym = KEYMAP[ch];
    if (sym) {
      e.preventDefault();
      setPart((p) => setSlot(p, sym));
    }
  };

  const composing = keys.length > 0 || partStr(part).length > 0;
  const pre = conv && conv.for === keys.join("|") ? conv.best : keys.map(keyToShown).join(" ");
  return (
    <div className={`ime ${className}`} style={style}>
      <button className="chip ime-mode" onClick={() => { setImeOn((x) => !x); reset(); ta.current?.focus(); }} title="Switch between the built-in 注音 keyboard and your system keyboard" type="button">
        {imeOn ? <span className="zh-ui" style={{ fontSize: 12 }}>注音</span> : "System"}
      </button>
      <textarea
        ref={ta}
        className="area"
        rows={rows}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        spellCheck={false}
        autoCorrect="off"
        autoCapitalize="off"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => setPicker(false)}
      />
      {imeOn && (
        <div className="ime-bar">
          {composing ? (
            <>
              {pre && <span className="pre">{pre}</span>}
              {partStr(part) && <span className="part">{partStr(part)}</span>}
              {picker ? (
                <span className="cands">
                  {pageCands.map((c, i) => (
                    <span key={c.word} className={`cand ${i === 0 ? "first" : ""}`} onMouseDown={(e) => { e.preventDefault(); pick(c); }}>
                      <small>{i + 1}</small>
                      {c.word}
                    </span>
                  ))}
                  {pages > 1 && <span className="hintline">{page + 1}/{pages} →</span>}
                </span>
              ) : (
                keys.length > 0 && (
                  <span className="cands">
                    {cands.slice(0, 6).map((c) => (
                      <span key={c.word} className="cand" style={{ fontSize: 16, color: "var(--muted)" }} onMouseDown={(e) => { e.preventDefault(); pick(c); }}>
                        {c.word}
                      </span>
                    ))}
                    <span className="hintline">↓ choose · Enter commit</span>
                  </span>
                )
              )}
            </>
          ) : early && !hint ? (
            <span className="hintline">Typing whole sentences in zhuyin is taught by unit {zy!.typing_from} of the zhuyin course (you are on unit {zy!.next ?? zy!.total}). Until then, the 注音 button switches to your own keyboard.</span>
          ) : (
            <span className="hintline">Space 1st tone · 6 ˊ · 3 ˇ · 4 ˋ · 7 ˙ · Shift+, ， · Shift+. 。 · Shift+/ ？ · ' 、 · [ ] 「」</span>
          )}
        </div>
      )}
    </div>
  );
}

interface KbProps {
  next?: string[]; // keys to press next (first one strongest)
  known?: string; // symbols learned so far; others are dimmed
  hit?: string; // key just pressed
  small?: boolean;
  labels?: boolean;
}

/** The 大千 layout. */
export function Keyboard({ next = [], known, hit, small, labels = true }: KbProps) {
  return (
    <div className={`kb ${small ? "sm" : ""}`}>
      {ROWS.map((row) => (
        <div key={row} className="kb-row">
          {row.split("").map((k) => {
            const sym = KEYMAP[k];
            const tone = TONE_LABEL[k];
            const dim = known != null && sym && !known.includes(sym);
            return (
              <div key={k} className={`key ${tone ? "tone" : ""} ${next[0] === k ? "hl" : next.includes(k) ? "next" : ""} ${dim ? "dim" : ""} ${hit === k ? "hit" : ""}`}>
                {labels && <small>{k}</small>}
                {sym || tone || ""}
              </div>
            );
          })}
        </div>
      ))}
      <div className="kb-row">
        <div className={`key space ${next[0] === " " ? "hl" : next.includes(" ") ? "next" : ""} ${hit === " " ? "hit" : ""}`}>space · 1st tone</div>
      </div>
    </div>
  );
}

/** Capture raw zhuyin from the keyboard (no conversion): for spelling drills. */
export function useRawZhuyin(onSyllable: (shown: string) => void, active = true) {
  const [part, setPart] = useState<Part>(EMPTY);
  const [hit, setHit] = useState("");
  const partRef = useRef(part);
  partRef.current = part;
  const cb = useRef(onSyllable);
  cb.current = onSyllable;
  useEffect(() => {
    if (!active) return;
    const on = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.code === "Backspace") {
        e.preventDefault();
        setPart((p) => (p.f ? { ...p, f: "" } : p.m ? { ...p, m: "" } : { ...p, i: "" }));
        return;
      }
      const ch = CODE2CHAR[e.code];
      if (ch === undefined || e.shiftKey) return;
      setHit(ch);
      window.setTimeout(() => setHit(""), 140);
      const tone = TONEKEYS[ch];
      if (tone) {
        e.preventDefault();
        const body = partStr(partRef.current);
        if (!body) return;
        setPart(EMPTY);
        cb.current(showSyllable(body, tone));
        return;
      }
      const sym = KEYMAP[ch];
      if (sym) {
        e.preventDefault();
        setPart((p) => setSlot(p, sym));
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [active]);
  return { partial: partStr(part), hit, clear: () => setPart(EMPTY) };
}
