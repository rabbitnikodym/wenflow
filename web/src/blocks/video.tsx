// Video player with synced, clickable captions (YouTube or a local file).
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { RubySwitch, Tokens } from "../han";
import { useApp } from "../store";
import { Icon, Loading, fmtTime, isTyping, useKey } from "../ui";

declare global {
  interface Window {
    YT: any;
    onYouTubeIframeAPIReady: any;
  }
}

let ytReady: Promise<void> | null = null;
function loadYT(): Promise<void> {
  if (window.YT?.Player) return Promise.resolve();
  if (!ytReady)
    ytReady = new Promise((resolve) => {
      const prev = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        prev?.();
        resolve();
      };
      const s = document.createElement("script");
      s.src = "https://www.youtube.com/iframe_api";
      document.head.appendChild(s);
    });
  return ytReady;
}

interface Ctl {
  time: () => number;
  seek: (t: number) => void;
  play: () => void;
  pause: () => void;
  rate: (r: number) => void;
  playing: () => boolean;
}

export const LEVEL_NAME: Record<number, string> = { 1: "Learner", 2: "Slow & clear", 3: "Clear native", 4: "Conversational", 5: "Fast native" };

export function VideoCard({ v, onOpen }: { v: any; onOpen: () => void }) {
  const state = v.job?.state;
  return (
    <div className="vcard" onClick={onOpen}>
      <div className="thumb" style={{ backgroundImage: v.thumbnail ? `url(${v.thumbnail})` : undefined }}>
        {v.duration > 0 && <span className="dur">{fmtTime(v.duration)}</span>}
      </div>
      <div className="ti">{v.title}</div>
      <div className="row wrap gap6 mt8">
        <span className="tiny muted" style={{ marginRight: 4 }}>{v.channel}</span>
        {v.coverage != null && <span className="chip">{Math.round(v.coverage * 100)}% known</span>}
        {v.coverage == null && v.meta?.channel_level && <span className="chip">{LEVEL_NAME[v.meta.channel_level]}</span>}
        {v.ready ? <span className="chip solid">Captions</span> : state === "working" || state === "queued" ? <span className="chip">Preparing…</span> : state === "error" ? <span className="chip bad">Failed</span> : null}
        {v.watched_at && <span className="chip">Watched</span>}
      </div>
    </div>
  );
}

export function Player({ videoId, onWatched }: { videoId: string; onWatched?: (seconds: number) => void }) {
  const { toast } = useApp();
  const [v, setV] = useState<any>(null);
  const [job, setJob] = useState<any>(null);
  const [err, setErr] = useState("");
  const [active, setActive] = useState(-1);
  const [loop, setLoop] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [hidden, setHidden] = useState(false);
  const [trans, setTrans] = useState<Record<number, string>>({});
  const [watched, setWatched] = useState(0);
  const ctl = useRef<Ctl | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const vid = useRef<HTMLVideoElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const hover = useRef(false);
  const loopRef = useRef(loop);
  loopRef.current = loop;
  const activeRef = useRef(active);
  activeRef.current = active;
  const watchedRef = useRef(0);

  // load, and wait for captions if they are still being prepared
  useEffect(() => {
    let live = true;
    let timer = 0;
    const load = async () => {
      try {
        const r = await api.get(`/videos/${videoId}`);
        if (!live) return;
        if (r.captions?.length) {
          setV(r);
          setJob(null);
          return;
        }
        setV(r);
        const j = r.job?.state && r.job.state !== "unknown" ? r.job : await api.post("/videos/import", { url: videoId });
        if (!live) return;
        setJob(j);
        poll();
      } catch (e: any) {
        if (e.status === 404) {
          try {
            const j = await api.post("/videos/import", { url: videoId });
            if (!live) return;
            setJob(j);
            poll();
          } catch (e2: any) {
            setErr(e2.message);
          }
        } else setErr(e.message);
      }
    };
    const poll = () => {
      timer = window.setTimeout(async () => {
        if (!live) return;
        const j = await api.get(`/videos/${videoId}/job`).catch(() => null);
        if (!live) return;
        if (j) setJob(j);
        if (j?.state === "ready") load();
        else if (j?.state === "error") setErr(j.error || "Could not prepare this video.");
        else poll();
      }, 1800);
    };
    load();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [videoId]);

  const caps: any[] = v?.captions || [];
  const local = v?.source === "local";

  // player
  useEffect(() => {
    if (!v) return;
    let player: any;
    let dead = false;
    if (local) {
      const el = vid.current!;
      ctl.current = {
        time: () => el.currentTime, seek: (t) => (el.currentTime = t), play: () => el.play(), pause: () => el.pause(),
        rate: (r) => (el.playbackRate = r), playing: () => !el.paused,
      };
    } else {
      loadYT().then(() => {
        if (dead || !host.current) return;
        const div = document.createElement("div");
        host.current.innerHTML = "";
        host.current.appendChild(div);
        player = new window.YT.Player(div, {
          videoId, width: "100%", height: "100%",
          playerVars: { playsinline: 1, rel: 0, modestbranding: 1, cc_load_policy: 0, iv_load_policy: 3 },
          events: {
            onReady: () => {
              ctl.current = {
                time: () => player.getCurrentTime?.() || 0, seek: (t) => player.seekTo(t, true), play: () => player.playVideo(),
                pause: () => player.pauseVideo(), rate: (r) => player.setPlaybackRate(r), playing: () => player.getPlayerState?.() === 1,
              };
            },
          },
        });
      });
    }
    return () => {
      dead = true;
      ctl.current = null;
      try {
        player?.destroy?.();
      } catch {
        /* already gone */
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [v?.id, local]);

  // sync captions to playback
  useEffect(() => {
    if (!caps.length) return;
    const id = window.setInterval(() => {
      const c = ctl.current;
      if (!c) return;
      const t = c.time();
      if (c.playing()) {
        watchedRef.current += 0.2;
        if (Math.floor(watchedRef.current) % 5 === 0) setWatched(Math.floor(watchedRef.current));
      }
      const cur = activeRef.current;
      if (loopRef.current && cur >= 0 && caps[cur] && t >= caps[cur].e + 0.12) {
        c.seek(caps[cur].s);
        return;
      }
      let lo = 0;
      let hi = caps.length - 1;
      let idx = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (caps[mid].s <= t + 0.05) {
          idx = mid;
          lo = mid + 1;
        } else hi = mid - 1;
      }
      if (idx !== cur) setActive(idx);
    }, 200);
    return () => window.clearInterval(id);
  }, [caps]);

  useEffect(() => {
    if (active < 0 || hover.current) return;
    list.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [active]);

  useEffect(
    () => () => {
      if (watchedRef.current > 20) api.post(`/videos/${videoId}/watched`, { seconds: Math.round(watchedRef.current) }).catch(() => {});
    },
    [videoId],
  );

  const jump = (i: number) => {
    const c = caps[Math.max(0, Math.min(caps.length - 1, i))];
    if (!c || !ctl.current) return;
    ctl.current.seek(c.s);
    ctl.current.play();
    setActive(Math.max(0, Math.min(caps.length - 1, i)));
  };
  const toggle = () => (ctl.current?.playing() ? ctl.current?.pause() : ctl.current?.play());
  const setRate = (r: number) => {
    setSpeed(r);
    ctl.current?.rate(r);
  };
  const translate = async (i: number) => {
    if (trans[i]) return setTrans((t) => ({ ...t, [i]: "" }));
    try {
      const r = await api.post("/translate", { text: caps[i].t });
      setTrans((t) => ({ ...t, [i]: r.en }));
    } catch (e: any) {
      toast(e.message);
    }
  };
  useKey((e) => {
    if (isTyping(e) || !caps.length) return;
    if (e.code === "ArrowLeft") { e.preventDefault(); jump(active - 1); }
    else if (e.code === "ArrowRight") { e.preventDefault(); jump(active + 1); }
    else if (e.code === "ArrowDown" || e.code === "KeyR") { e.preventDefault(); jump(Math.max(0, active)); }
    else if (e.code === "Space") { e.preventDefault(); toggle(); }
    else if (e.code === "KeyL") setLoop((x) => !x);
    else if (e.code === "KeyH") setHidden((x) => !x);
  });

  const unknown = useMemo(() => new Set<string>(v?.meta?.unknown || []), [v]);

  if (err)
    return (
      <div className="page narrow">
        <div className="error">{err}</div>
        <p className="muted small mt8">Some videos block downloads or have no speech. Try another one.</p>
      </div>
    );
  if (!v && !job) return <Loading label="Opening video" />;
  const cur = active >= 0 ? caps[active] : null;
  return (
    <div className="watch">
      <div className="left">
        <div className="frame">
          {local ? <video ref={vid} src={v.url} controls /> : <div ref={host} />}
        </div>
        <div className="now">
          {!caps.length ? (
            <div className="col gap12">
              <div className="row gap12"><span className="spinner" /><span className="label">{job?.step || "Preparing captions"}</span></div>
              <p className="small muted prose">
                Videos without a Chinese caption track are transcribed on this computer with Whisper. That usually takes under a minute; you can start watching meanwhile.
              </p>
            </div>
          ) : (
            <>
              <div className="row between wrap gap12">
                <div className="row gap4">
                  <button className="icon-btn" onClick={() => jump(active - 1)} title="Previous line (←)">{Icon.left}</button>
                  <button className="icon-btn" onClick={() => jump(Math.max(0, active))} title="Replay line (R)">{Icon.repeat}</button>
                  <button className="icon-btn" onClick={() => jump(active + 1)} title="Next line (→)">{Icon.right}</button>
                  <button className={`btn sm ${loop ? "on" : ""}`} onClick={() => setLoop((x) => !x)} title="Loop this line (L)">Loop</button>
                  <button className={`btn sm ${speed < 1 ? "on" : ""}`} onClick={() => setRate(speed === 1 ? 0.75 : speed === 0.75 ? 0.5 : 1)}>{speed}×</button>
                  <button className={`btn sm ${hidden ? "on" : ""}`} onClick={() => setHidden((x) => !x)} title="Listen first, read after (H)">Hide text</button>
                </div>
                <RubySwitch />
              </div>
              <div style={{ minHeight: 120 }}>
                {cur ? (
                  hidden ? (
                    <button className="btn" onClick={() => setHidden(false)}>Reveal line</button>
                  ) : (
                    <div onClick={() => ctl.current?.pause()}>
                      <Tokens tokens={cur.tokens} size="l" unknown={unknown} />
                      <div className="row gap12 mt8">
                        <button className="btn ghost sm" style={{ padding: 0 }} onClick={() => translate(active)}>{trans[active] ? "Hide English" : "Translate"}</button>
                      </div>
                      {trans[active] && <div className="muted mt4">{trans[active]}</div>}
                    </div>
                  )
                ) : (
                  <div className="muted small">Press play. Lines appear here as they are spoken — click any word for its meaning.</div>
                )}
              </div>
              <div className="row between wrap gap12 tiny muted upper">
                <span>{v.caption_source === "whisper" ? "Transcribed with Whisper" : v.caption_source === "auto" ? "Auto captions" : "Creator's subtitles"}</span>
                {v.coverage != null && <span className="num">{Math.round(v.coverage * 100)}% of words known · {v.meta?.cpm || "–"} 字/分</span>}
                <span className="num">Watched {fmtTime(watched)}</span>
              </div>
              {onWatched && (
                <div className="row end"><button className="btn primary" onClick={() => onWatched(Math.round(watchedRef.current))}>Done watching</button></div>
              )}
            </>
          )}
        </div>
      </div>
      <div className="caps" ref={list} onMouseEnter={() => (hover.current = true)} onMouseLeave={() => (hover.current = false)}>
        <div className="pad rule-b">
          <div className="zh-ui" style={{ fontSize: 16, lineHeight: 1.5 }}>{v?.title}</div>
          <div className="tiny muted mt4">{v?.channel}</div>
        </div>
        {caps.map((c, i) => (
          <div key={i} data-i={i} className={`cap ${i === active ? "on" : ""}`} onClick={() => jump(i)}>
            <span className="ts">{fmtTime(c.s)}</span>
            {hidden && i !== active ? <span className="faint">· · ·</span> : <Tokens tokens={c.tokens} size="s" plain={i !== active} unknown={i === active ? unknown : undefined} />}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Lesson block: choose one of today's videos and watch it. */
export function VideoBlock({ payload, onDone }: { payload: any; onDone: (d?: any) => void }) {
  const [list, setList] = useState<any[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/videos/daily").then((r) => setList(r.videos)).catch((e) => setErr(e.message));
  }, []);
  if (open) return <Player videoId={open} onWatched={(s) => onDone({ seconds: s, video: open })} />;
  if (err) return <div className="stage-inner col gap16"><div className="error">{err}</div><button className="btn" onClick={() => onDone({ skipped: true })}>Skip</button></div>;
  if (!list) return <Loading label="Finding today's videos" />;
  return (
    <div className="stage-inner wide col gap24">
      <div>
        <div className="eyebrow">Immersion</div>
        <h1 className="h1 mt8">Watch for {payload.watch_minutes || 8} minutes</h1>
        <p className="muted mt8 prose">Fresh videos from Taiwanese creators, chosen for where you are in the year. Captions follow along and every word is clickable.</p>
      </div>
      {list.length === 0 ? (
        <div className="muted">No suggestions could be fetched right now. Paste any YouTube link in the Watch tab instead.</div>
      ) : (
        <div className="grid3">
          {list.map((v) => (
            <VideoCard key={v.id} v={v} onOpen={() => setOpen(v.id)} />
          ))}
        </div>
      )}
      <div className="row end"><button className="btn ghost sm" onClick={() => onDone({ skipped: true })}>Skip today</button></div>
    </div>
  );
}
