// Stroke-order animation and handwriting quiz (Hanzi Writer).
import HanziWriter from "hanzi-writer";
import { useEffect, useRef, useState } from "react";

function colors() {
  const cs = getComputedStyle(document.documentElement);
  return { stroke: cs.getPropertyValue("--text").trim() || "#fff", outline: cs.getPropertyValue("--line-strong").trim() || "#444", hl: cs.getPropertyValue("--muted").trim() || "#888" };
}

interface Props {
  char: string;
  mode: "quiz" | "show";
  size?: number;
  outline?: boolean; // show the faint character outline while quizzing
  onComplete?: (mistakes: number) => void;
  runKey?: any; // change to restart
}

export function HanziWrite({ char, mode, size = 220, outline = false, onComplete, runKey }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [missing, setMissing] = useState(false);
  const done = useRef(onComplete);
  done.current = onComplete;
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.innerHTML = "";
    setMissing(false);
    const c = colors();
    let cancelled = false;
    const w = HanziWriter.create(el, char, {
      width: size, height: size, padding: 10, strokeColor: c.stroke, outlineColor: c.outline, drawingColor: c.stroke,
      highlightColor: c.hl, radicalColor: c.stroke, showOutline: mode === "show" || outline, showCharacter: mode === "show",
      strokeAnimationSpeed: 1.4, delayBetweenStrokes: 120, drawingWidth: 5, showHintAfterMisses: 2,
      onLoadCharDataError: () => !cancelled && setMissing(true),
    });
    if (mode === "quiz") {
      w.quiz({
        leniency: 1.25,
        onComplete: (s: any) => !cancelled && done.current?.(s.totalMistakes || 0),
      });
    } else {
      w.animateCharacter();
    }
    return () => {
      cancelled = true;
      try {
        w.cancelQuiz();
      } catch {
        /* not quizzing */
      }
      el.innerHTML = "";
    };
  }, [char, mode, size, outline, runKey]);
  return (
    <div className={`writer-box ${size < 200 ? "sm" : ""}`} style={{ width: size, height: size }}>
      <div ref={box} />
      {missing && (
        <div className="center muted small" style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
          <span>
            No stroke data for <span className="zh" style={{ fontSize: 28 }}>{char}</span>
          </span>
        </div>
      )}
    </div>
  );
}

/** Practise writing one character: watch the strokes, then write it from memory. */
export function WritePractice({ char, hint, onDone, size = 220 }: { char: string; hint?: any; onDone?: (mistakes: number) => void; size?: number }) {
  const [mode, setMode] = useState<"quiz" | "show">("quiz");
  const [run, setRun] = useState(0);
  const [result, setResult] = useState<number | null>(null);
  useEffect(() => {
    setMode("quiz");
    setResult(null);
    setRun((r) => r + 1);
  }, [char]);
  return (
    <div className="row gap24 top wrap">
      <HanziWrite char={char} mode={mode} size={size} runKey={run} onComplete={(m) => { setResult(m); onDone?.(m); }} />
      <div className="col gap12" style={{ minWidth: 180 }}>
        {hint}
        <div className="row gap8 wrap">
          <button className="btn sm" onClick={() => { setMode("show"); setRun((r) => r + 1); }}>Show strokes</button>
          <button className="btn sm" onClick={() => { setMode("quiz"); setResult(null); setRun((r) => r + 1); }}>Write again</button>
        </div>
        {result != null && <div className="small muted">{result === 0 ? "Perfect — no mistakes." : `${result} stroke ${result === 1 ? "mistake" : "mistakes"}.`}</div>}
        {mode === "quiz" && result == null && <div className="small faint">Draw each stroke with the mouse or your finger. A hint appears after two misses.</div>}
      </div>
    </div>
  );
}
