// Microphone recording and tone feedback.
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Tok, Tokens } from "./han";
import { Icon, Speak, audioPlaying, isTyping, useKey } from "./ui";

export function useRecorder() {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState("");
  const stream = useRef<MediaStream | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  useEffect(
    () => () => {
      stream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  const start = useCallback(async () => {
    setError("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser cannot record audio here. Open the app at http://localhost:8000.");
      if (!stream.current || !stream.current.active)
        stream.current = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((m) => MediaRecorder.isTypeSupported(m));
      const r = new MediaRecorder(stream.current, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      r.start();
      rec.current = r;
      setRecording(true);
      return true;
    } catch (e: any) {
      setError(e?.name === "NotAllowedError" ? "Microphone access was blocked. Allow it in the browser's site settings." : e?.message || "Could not start recording.");
      return false;
    }
  }, []);

  const stop = useCallback(
    () =>
      new Promise<Blob | null>((resolve) => {
        const r = rec.current;
        if (!r || r.state === "inactive") {
          setRecording(false);
          resolve(null);
          return;
        }
        r.onstop = () => {
          setRecording(false);
          resolve(new Blob(chunks.current, { type: r.mimeType || "audio/webm" }));
        };
        r.stop();
      }),
    [],
  );

  return { recording, start, stop, error };
}

/** Round microphone button: click (or press Space) to start, again to stop.
 *  With `handsFree` it listens continuously instead: recording starts when you speak and is sent
 *  after a pause, and it stays quiet while the tutor is talking. */
export function MicButton({ onAudio, busy, small, hotkey = true, handsFree = false }: { onAudio: (b: Blob) => void; busy?: boolean; small?: boolean; hotkey?: boolean; handsFree?: boolean }) {
  const { recording, start, stop, error } = useRecorder();
  const [level, setLevel] = useState(0);
  const live = useRef({ busy: !!busy, recording, onAudio });
  live.current = { busy: !!busy, recording, onAudio };

  const toggle = async () => {
    if (busy) return;
    if (recording) {
      const b = await stop();
      if (b && b.size > 800) onAudio(b);
    } else await start();
  };
  useKey((e) => {
    if (!hotkey || handsFree || isTyping(e) || e.code !== "Space" || e.repeat) return;
    e.preventDefault();
    toggle();
  });

  // Voice activity detection for hands-free mode.
  useEffect(() => {
    if (!handsFree) return;
    let dead = false;
    let ctx: AudioContext | null = null;
    let stream: MediaStream | null = null;
    let timer = 0;
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
      } catch {
        return;
      }
      if (dead) return stream.getTracks().forEach((t) => t.stop());
      ctx = new AudioContext();
      const an = ctx.createAnalyser();
      an.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(an);
      const buf = new Float32Array(an.fftSize);
      // The recorder runs whenever it is the learner's turn, so the first syllable is never clipped.
      // A take is sent once speech has been heard and then a pause follows; silent takes are discarded.
      let floor = 0.01;
      let loud = 0;
      let quiet = 0;
      let spoke = false;
      let armedAt = 0;
      let working = false;
      timer = window.setInterval(async () => {
        if (working) return;
        an.getFloatTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        const rms = Math.sqrt(sum / buf.length);
        setLevel(rms);
        const st = live.current;
        working = true;
        try {
          if (st.busy || audioPlaying()) {
            if (st.recording) await stop(); // the tutor is thinking or talking: drop this take
            loud = quiet = 0;
            spoke = false;
            return;
          }
          if (!st.recording) {
            loud = quiet = 0;
            spoke = false;
            armedAt = Date.now();
            await start();
            return;
          }
          const thr = Math.max(0.018, floor * 3.2);
          if (!spoke) {
            floor = 0.97 * floor + 0.03 * Math.min(rms, 0.05);
            loud = rms > thr ? loud + 1 : 0;
            if (loud >= 3) spoke = true;
            else if (Date.now() - armedAt > 6000) await stop(); // nothing said: start a fresh take
            return;
          }
          quiet = rms > thr * 0.7 ? 0 : quiet + 1;
          if (quiet >= 22 || Date.now() - armedAt > 40000) {
            const b = await stop();
            spoke = false;
            if (b && b.size > 1500) live.current.onAudio(b);
          }
        } finally {
          working = false;
        }
      }, 50);
    })();
    return () => {
      dead = true;
      window.clearInterval(timer);
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close().catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handsFree]);

  const ring = handsFree && !recording && !busy ? { boxShadow: `0 0 0 ${Math.min(14, Math.round(level * 220))}px color-mix(in srgb, var(--text) 12%, transparent)` } : undefined;
  return (
    <div className="col gap8" style={{ alignItems: "center" }}>
      <button className={`mic ${small ? "sm" : ""} ${recording ? "rec" : ""} ${busy ? "busy" : ""}`} onClick={toggle} title={handsFree ? "Listening" : "Record (Space)"} style={ring}>
        {busy ? <span className="spinner" /> : recording ? Icon.stop : Icon.mic}
      </button>
      <div className="tiny muted upper" style={{ letterSpacing: ".2em" }}>
        {busy ? "Thinking…" : recording ? (handsFree ? "Listening…" : "Tap to stop") : handsFree ? "Just speak" : hotkey ? "Tap or Space" : "Tap to speak"}
      </div>
      {error && <div className="error center" style={{ maxWidth: 280 }}>{error}</div>}
    </div>
  );
}

const TEMPLATES: Record<number, number[]> = {
  1: [2.5, 2.6, 2.6, 2.6, 2.5],
  2: [-1.0, -0.8, 0.5, 2.0, 3.5],
  3: [-1.5, -3.0, -4.0, -4.0, -3.0],
  4: [4.0, 3.0, 1.0, -1.0, -3.5],
};
const TONE_NAME: Record<number, string> = { 1: "1st ˉ", 2: "2nd ˊ", 3: "3rd ˇ", 4: "4th ˋ", 5: "neutral" };
const MARK: Record<number, string> = { 0: "?", 1: "ˉ", 2: "ˊ", 3: "ˇ", 4: "ˋ", 5: "˙" };

function Contour({ pts, expected }: { pts?: number[] | null; expected?: number }) {
  const w = 44;
  const h = 26;
  const y = (v: number) => h / 2 - Math.max(-6, Math.min(6, v)) * (h / 13);
  const path = (a: number[]) => a.map((v, i) => `${i ? "L" : "M"}${(i * (w - 4)) / (a.length - 1) + 2},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h}>
      {expected && TEMPLATES[expected] && <path d={path(TEMPLATES[expected])} fill="none" stroke="var(--faint)" strokeWidth="1" strokeDasharray="2 2" />}
      {pts && <path d={path(pts)} fill="none" stroke="currentColor" strokeWidth="1.6" />}
    </svg>
  );
}

export interface Syl {
  c: string;
  py: string;
  expected: number;
  detected: number | null;
  ok: boolean | null;
  sure?: boolean;
  contour?: number[] | null;
  heard?: string | null;
}

/** Per-syllable tone verdicts with the pitch contour you produced (solid) against the target shape (dashed).
 *  Only confident mismatches are flagged; borderline ones get a quiet "~". `compact` lists just the
 *  flagged syllables until expanded (used inside conversations). */
export function ToneReport({ syllables, score, compact }: { syllables: Syl[]; score?: number | null; compact?: boolean }) {
  const [open, setOpen] = useState(!compact);
  if (!syllables?.length) return null;
  const wrong = syllables.filter((s) => s.ok === false && s.sure);
  const graded = syllables.filter((s) => s.ok != null).length;
  const unsure = syllables.filter((s) => s.ok === false && !s.sure).length;
  return (
    <div className="col gap8">
      <div className="row between">
        <span className="label">Tones</span>
        <span className="row gap12">
          {graded > 0 && (
            <span className="small num">
              {wrong.length === 0 ? "no clear slips" : `${wrong.length} clear ${wrong.length === 1 ? "slip" : "slips"}`}
              {unsure > 0 ? ` · ${unsure} uncertain` : ""} · {graded} syllables
            </span>
          )}
          {compact && <button className="btn ghost sm" style={{ height: 22, padding: 0 }} onClick={() => setOpen((x) => !x)}>{open ? "Hide" : "Every syllable"}</button>}
        </span>
      </div>
      {open && (
        <div className="syls">
          {syllables.map((s, i) => {
            const bad = s.ok === false && s.sure;
            const unsure = s.ok === false && !s.sure;
            return (
              <div key={i} className={`syl ${bad ? "bad" : s.ok ? "ok" : ""}`} title={s.detected ? `Target ${TONE_NAME[s.expected]}, heard ${TONE_NAME[s.detected]}${unsure ? " (not certain)" : ""}` : "Not heard clearly"}>
                <div className="c">{s.c}</div>
                <div className="p">{s.py}</div>
                <Contour pts={s.contour} expected={s.expected} />
                <div className="v">{bad ? `${MARK[s.detected || 0]} → ${MARK[s.expected]}` : s.ok ? "✓" : unsure ? "~" : "–"}</div>
              </div>
            );
          })}
        </div>
      )}
      {wrong.length > 0 ? (
        <div className="small muted">
          {wrong.slice(0, 5).map((s, i) => (
            <span key={i}>
              {i > 0 && " · "}
              <span className="zh" style={{ color: "var(--text)", fontSize: 16 }}>{s.c}</span> came out as {TONE_NAME[s.detected || 0]}, aim for {TONE_NAME[s.expected]}
            </span>
          ))}
          . Listen to the model again and compare.
        </div>
      ) : (
        graded > 0 && <div className="small muted">No clear tone slips. {syllables.some((s) => s.ok === false) ? "A “~” marks syllables the detector was unsure about." : ""}</div>
      )}
    </div>
  );
}

/** Listen, repeat, get tone feedback for one sentence. */
export function ShadowLine({ zh, en, tokens, onResult, big }: { zh: string; en?: string; tokens?: Tok[]; onResult?: (score: number | null) => void; big?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    setRes(null);
    setErr("");
  }, [zh]);
  const send = async (blob: Blob) => {
    setBusy(true);
    setErr("");
    try {
      const f = new FormData();
      f.append("audio", blob, "speech.webm");
      f.append("target", zh);
      const r = await api.form("/speech/analyze", f);
      if (r.error) setErr(r.error);
      else {
        setRes(r);
        onResult?.(r.score);
      }
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy(false);
  };
  return (
    <div className="col gap24">
      <div>
        {tokens ? <Tokens tokens={tokens} size={big ? "xl" : "l"} /> : <div className={`han-text ${big ? "xl" : "l"}`}>{zh}</div>}
        {en && <div className="muted mt8">{en}</div>}
      </div>
      <div className="row gap24 wrap">
        <MicButton onAudio={send} busy={busy} />
        <div className="col gap8">
          <Speak text={zh} label="Listen" />
          <Speak text={zh} slow label="Slow" />
        </div>
      </div>
      {err && <div className="error">{err}</div>}
      {res && (
        <div className="col gap16">
          <div>
            <div className="label mb8">Heard</div>
            <div className="han-text s">{res.asr?.text || "—"}</div>
            {res.char_match != null && res.char_match < 0.7 && (
              <div className="small muted mt4">The recogniser heard something different from the target, so some syllables could not be graded.</div>
            )}
          </div>
          <ToneReport syllables={res.syllables} score={res.score} />
        </div>
      )}
    </div>
  );
}
