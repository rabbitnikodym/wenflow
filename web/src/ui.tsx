// Small shared primitives.
import { useCallback, useEffect, useRef, useState } from "react";
import { ttsUrl } from "./api";

export const Icon = {
  play: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M7 5l12 7-12 7V5z" /></svg>
  ),
  pause: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M8 5v14M16 5v14" /></svg>
  ),
  sound: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M4 9v6h4l5 4V5L8 9H4z" /><path d="M16.5 8.5a5 5 0 010 7M19 6a8.5 8.5 0 010 12" />
    </svg>
  ),
  mic: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0M12 18v3" />
    </svg>
  ),
  stop: (
    <svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="7" width="10" height="10" /></svg>
  ),
  plus: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M12 5v14M5 12h14" /></svg>
  ),
  check: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
  ),
  x: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M6 6l12 12M18 6L6 18" /></svg>
  ),
  left: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M15 5l-7 7 7 7" /></svg>
  ),
  right: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M9 5l7 7-7 7" /></svg>
  ),
  repeat: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M4 12a8 8 0 0113.7-5.7L20 8M20 4v4h-4M20 12a8 8 0 01-13.7 5.7L4 16M4 20v-4h4" />
    </svg>
  ),
  trash: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" /></svg>
  ),
  globe: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c3 3 3 14 0 17M12 3.5c-3 3-3 14 0 17" />
    </svg>
  ),
};

// One shared audio element so a new clip always replaces the one that is playing.
let player: HTMLAudioElement | null = null;
export function playAudio(url: string, rate = 1): Promise<void> {
  return new Promise((resolve) => {
    if (!player) player = new Audio();
    player.pause();
    player.src = url;
    player.playbackRate = rate;
    player.onended = () => resolve();
    player.onerror = () => resolve();
    player.play().catch(() => resolve());
  });
}
export const stopAudio = () => player?.pause();
export const audioPlaying = () => !!player && !player.paused && !player.ended;
export const say = (text: string, slow = false) => playAudio(ttsUrl(text, slow ? -30 : undefined));
/** The name of a zhuyin symbol as it is recited: bo, po, mo, fo … */
export const saySymbol = (sym: string) => playAudio(`/api/tts/symbol/${encodeURIComponent(sym)}`);

export function Speak({ text, slow, label, className = "" }: { text: string; slow?: boolean; label?: string; className?: string }) {
  const [busy, setBusy] = useState(false);
  const run = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setBusy(true);
    await say(text, slow);
    setBusy(false);
  };
  if (label)
    return (
      <button className={`btn sm ${className}`} onClick={run} disabled={busy}>
        {Icon.sound}
        <span>{label}</span>
      </button>
    );
  return (
    <button className={`icon-btn ${busy ? "on" : ""} ${className}`} onClick={run} title={slow ? "Play slowly" : "Play"}>
      {Icon.sound}
    </button>
  );
}

export function Bar({ value, thick }: { value: number; thick?: boolean }) {
  return (
    <div className={`bar ${thick ? "thick" : ""}`}>
      <i style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading">
      <span className="spinner" />
      <span className="label">{label}</span>
    </div>
  );
}

export function Seg<T extends string>({ value, options, onChange }: { value: T; options: { v: T; l: any }[]; onChange: (v: T) => void }) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button key={o.v} className={value === o.v ? "on" : ""} onClick={() => onChange(o.v)}>
          {o.l}
        </button>
      ))}
    </div>
  );
}

/** Load data once (or when deps change). */
export function useLoad<T = any>(fn: () => Promise<T>, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await fn());
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

/** Window keydown handler that always sees the latest closure. */
export function useKey(handler: (e: KeyboardEvent) => void, active = true) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!active) return;
    const on = (e: KeyboardEvent) => ref.current(e);
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [active]);
}

export const isTyping = (e: KeyboardEvent) => {
  const t = e.target as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
};

export function fmtTime(sec: number) {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export interface McqItem {
  prompt?: string;
  sub?: string;
  q?: string;
  options: string[];
  answer: number;
  explain?: string;
  say?: string;
  symbol?: string; // a zhuyin symbol whose name is played once answered
}

/** A single multiple-choice question; number keys 1-4 answer it. */
export function Mcq({ item, onAnswer, zhOptions, big }: { item: McqItem; onAnswer: (ok: boolean) => void; zhOptions?: boolean; big?: boolean }) {
  const [picked, setPicked] = useState<number | null>(null);
  useEffect(() => setPicked(null), [item]);
  const choose = (i: number) => {
    if (picked != null) return;
    setPicked(i);
    if (item.symbol) saySymbol(item.symbol);
    else if (item.say) say(item.say);
    const ok = i === item.answer;
    window.setTimeout(() => onAnswer(ok), ok ? 650 : 1500);
  };
  useKey((e) => {
    if (isTyping(e)) return;
    const n = parseInt(e.key, 10);
    if (n >= 1 && n <= item.options.length) choose(n - 1);
  });
  return (
    <div className="col gap16">
      <div className={`opts ${item.options.length === 4 && !item.options.some((o) => o.length > 14) ? "two" : ""}`}>
        {item.options.map((o, i) => (
          <button
            key={i}
            className={`opt ${zhOptions ? "zh" : ""} ${picked != null && i === item.answer ? "right" : ""} ${picked === i && i !== item.answer ? "wrong" : ""}`}
            onClick={() => choose(i)}
            disabled={picked != null}
            style={big ? { fontSize: 24, padding: "22px 24px" } : undefined}
          >
            <span className="k">{i + 1}</span>
            <span>{o}</span>
          </button>
        ))}
      </div>
      {picked != null && item.explain && <div className="small muted">{item.explain}</div>}
    </div>
  );
}

/** Step through a list of items; calls onDone(score 0-1) at the end. */
export function useSteps(n: number) {
  const [i, setI] = useState(0);
  const [right, setRight] = useState(0);
  const next = (ok = true) => {
    if (ok) setRight((r) => r + 1);
    setI((x) => x + 1);
  };
  return { i, right, next, done: i >= n, reset: () => { setI(0); setRight(0); } };
}
