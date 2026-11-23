// Progress through the year, and settings.
import { useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import { Bar, Loading, Seg, say, useLoad } from "../ui";

function DeckRow({ label, zh, d }: { label: string; zh: string; d: any }) {
  const v = d.total ? d.learned / d.total : 0;
  return (
    <div className="item">
      <div style={{ width: 220 }}>
        <div className="h2">{label}</div>
        <div className="zh muted">{zh}</div>
      </div>
      <div className="grow"><Bar value={v} thick /></div>
      <div className="num small" style={{ width: 120, textAlign: "right" }}>{d.learned.toLocaleString()} <span className="muted">/ {d.total.toLocaleString()}</span></div>
    </div>
  );
}

function Spark({ pts, w = 520, h = 90 }: { pts: number[]; w?: number; h?: number }) {
  if (pts.length < 2) return <div className="muted small">Type a few sessions to see your speed over time.</div>;
  const max = Math.max(...pts, 10);
  const x = (i: number) => (i / (pts.length - 1)) * (w - 8) + 4;
  const y = (v: number) => h - 6 - (v / max) * (h - 16);
  return (
    <svg width={w} height={h} style={{ maxWidth: "100%" }}>
      <line x1="0" x2={w} y1={h - 6} y2={h - 6} stroke="var(--line)" />
      <path d={pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} fill="none" stroke="var(--text)" strokeWidth="1.5" />
      {pts.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r="2" fill="var(--text)" />)}
    </svg>
  );
}

export function Progress() {
  const { data } = useLoad(() => api.get("/progress"), []);
  const cur = useLoad(() => api.get("/curriculum"), []);
  const past = useLoad(() => api.get("/lessons"), []);
  const [openWeek, setOpenWeek] = useState<number | null>(null);
  if (!data || !cur.data) return <div className="page"><Loading /></div>;
  const s = data.summary;
  const week = s.week;
  const days: Record<string, number> = {};
  for (const d of data.days) days[d.day] = d.seconds;
  const cells: { day: string; lvl: number }[] = [];
  const today = new Date();
  const startDow = (today.getDay() + 6) % 7;
  for (let i = 83 + (6 - startDow); i >= -(6 - startDow); i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const sec = days[key] || 0;
    cells.push({ day: key, lvl: i < 0 ? -1 : sec === 0 ? 0 : sec < 600 ? 1 : sec < 1200 ? 2 : sec < 1800 ? 3 : 4 });
  }
  const typing = data.typing as any[];
  const lastCpm = typing.length ? typing[typing.length - 1].cpm : 0;
  const weeks: any[] = cur.data.weeks;
  const phases = cur.data.phases;
  return (
    <div className="page">
      <div className="eyebrow">進度</div>
      <h1 className="display mt16">Progress</h1>
      <div className="grid4 mt32">
        <div className="stat"><div className="v">{Math.max(s.day, 0)}<small>/ 364</small></div><div className="l">Lessons</div></div>
        <div className="stat"><div className="v">{s.streak}</div><div className="l">Day streak</div></div>
        <div className="stat"><div className="v">{data.total_hours}<small>h</small></div><div className="l">Time studied</div></div>
        <div className="stat"><div className="v">{Math.round(lastCpm)}<small>字/分</small></div><div className="l">Typing speed</div></div>
      </div>
      <div className="section mt48">
        <div className="row between base mb16">
          <div className="h2">The year · week {week} of 52</div>
          <span className="tiny muted upper">{phases[s.phase]?.name} — {phases[s.phase]?.zh}</span>
        </div>
        <div className="year">
          {weeks.map((w) => (
            <i key={w.week} className={`${w.week < week ? "done" : ""} ${w.week === week ? "cur" : ""}`} title={`Week ${w.week}: ${w.title}`} onClick={() => setOpenWeek(w.week)} style={{ cursor: "pointer" }} />
          ))}
        </div>
        <p className="small muted mt16 prose">{phases[s.phase]?.about} {s.start_date ? `Started ${s.start_date}; ${s.on_pace ? "you are on pace." : `day ${s.days_elapsed} on the calendar, lesson ${s.day} — an extra lesson now and then closes the gap.`}` : ""}</p>
      </div>
      <div className="section">
        <div className="h2 mb16">What you have covered</div>
        <div className="list">
          <DeckRow label="Traditional characters" zh="簡體 → 繁體" d={data.decks.char} />
          <DeckRow label="Taiwan vocabulary" zh="台灣用語" d={data.decks.tw} />
          <DeckRow label="HSK 6 vocabulary" zh="進階詞彙" d={data.decks.hsk6} />
          <DeckRow label="Words for the novel" zh="那些年" d={data.decks.book} />
          <DeckRow label="Taiwan readings" zh="讀音" d={data.decks.pron} />
          <DeckRow label="Grammar points" zh="語法" d={data.decks.grammar} />
        </div>
        <div className="grid4 mt32">
          <div className="stat"><div className="v">{data.srs.total}</div><div className="l">Cards</div></div>
          <div className="stat"><div className="v">{data.srs.mature}</div><div className="l">Mature cards</div></div>
          <div className="stat"><div className="v">{data.videos_watched}</div><div className="l">Videos watched</div></div>
          <div className="stat"><div className="v">{data.conversations}</div><div className="l">Conversations</div></div>
        </div>
      </div>
      <div className="section">
        <div className="grid2">
          <div>
            <div className="h2 mb16">Last twelve weeks</div>
            <div className="heat">{cells.map((c) => <i key={c.day} className={c.lvl > 0 ? `l${c.lvl}` : ""} style={c.lvl < 0 ? { visibility: "hidden" } : undefined} title={`${c.day}: ${Math.round((days[c.day] || 0) / 60)} min`} />)}</div>
            <div className="tiny muted mt12 upper">Darker = more minutes · 30 a day is the plan</div>
          </div>
          <div>
            <div className="h2 mb16">Zhuyin typing speed</div>
            <Spark pts={typing.map((t) => t.cpm)} />
            <div className="tiny muted mt12 upper">Targets: 15 字/分 month 1 · 30 month 4 · 45 month 8 · 60 by the end</div>
          </div>
        </div>
      </div>
      {past.data?.length > 0 && (
        <div className="section">
          <div className="h2 mb16">Lessons so far</div>
          <div className="list" style={{ maxHeight: 320, overflow: "auto" }}>
            {past.data.map((l: any) => (
              <a key={l.day} className="item click" style={{ padding: "10px 0" }} href={`#/day/${l.day}`}>
                <span className="idx">{String(l.day).padStart(3, "0")}</span>
                <span className="tiny muted num" style={{ width: 96 }}>{l.date}</span>
                <span className="grow small">Week {l.week} · {l.title}</span>
                <span className="tiny muted num">{l.done} / {l.blocks}</span>
                <span className="chip" style={{ visibility: l.status === "done" ? "visible" : "hidden" }}>Done</span>
              </a>
            ))}
          </div>
        </div>
      )}
      <div className="section">
        <div className="h2 mb16">Curriculum</div>
        {[0, 1, 2, 3, 4].map((p) => (
          <div key={p} className="mb24">
            <div className="row gap16 base mb8">
              <span className="label">Phase {p + 1} · weeks {phases[p].weeks}</span>
              <span className="h3">{phases[p].name}</span>
              <span className="zh muted">{phases[p].zh}</span>
            </div>
            <div className="list">
              {weeks.filter((w) => w.phase === p).map((w) => (
                <div key={w.week}>
                  <div className="item click" style={{ padding: "10px 0" }} onClick={() => setOpenWeek(openWeek === w.week ? null : w.week)}>
                    <span className="idx">{String(w.week).padStart(2, "0")}</span>
                    <span className="grow"><span className="zh" style={{ fontSize: 17 }}>{w.title_zh}</span> <span className="small muted" style={{ marginLeft: 10 }}>{w.title}</span></span>
                    {w.milestone && <span className="chip">Checkpoint</span>}
                    {w.week === week && <span className="chip solid">Now</span>}
                    {w.week < week && <span className="chip">Done</span>}
                  </div>
                  {openWeek === w.week && (
                    <div className="col gap12 small" style={{ padding: "4px 0 24px 54px", maxWidth: 820 }}>
                      <p className="prose">{w.theme}</p>
                      <ul className="muted zh-ui" style={{ margin: 0, paddingLeft: 18 }}>{(w.goals || []).map((g: string, i: number) => <li key={i}>{g}</li>)}</ul>
                      {w.zhuyin_focus && <div><span className="label">Zhuyin</span> <span className="muted zh-ui">{w.zhuyin_focus}</span></div>}
                      {w.traditional_focus && <div><span className="label">Traditional</span> <span className="muted zh-ui">{w.traditional_focus}</span></div>}
                      {w.speaking_focus && <div><span className="label">Speaking</span> <span className="muted zh-ui">{w.speaking_focus}</span></div>}
                      {w.writing_task && <div><span className="label">Writing</span> <span className="muted zh-ui">{w.writing_task}</span></div>}
                      {w.book_target && w.book_target !== "0%" && <div><span className="label">Novel</span> <span className="muted">{w.book_target} read by the end of the week</span></div>}
                      {w.milestone && <div><span className="label">Milestone</span> <span className="muted zh-ui">{w.milestone}</span></div>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: any }) {
  return (
    <div className="item top">
      <div style={{ width: 300, flex: "none" }}>
        <div className="h2">{label}</div>
        {hint && <div className="small muted mt4">{hint}</div>}
      </div>
      <div className="grow">{children}</div>
    </div>
  );
}

export function Settings() {
  const { settings, set, state, refresh } = useApp();
  const sv = state?.services;
  return (
    <div className="page narrow">
      <div className="eyebrow">設定</div>
      <h1 className="display mt16">Settings</h1>
      <div className="list mt32">
        <Row label="Readings" hint="Shown beside characters everywhere: lessons, articles, captions.">
          <Seg value={settings.ruby} onChange={(v) => set({ ruby: v })} options={[{ v: "zhuyin", l: <span className="zh">注音</span> }, { v: "pinyin", l: "Pīnyīn" }, { v: "none", l: "Off" }]} />
        </Row>
        <Row label="Pinyin while you learn zhuyin" hint={`With 注音 readings, a syllable keeps its pinyin until every symbol in it has been taught in the zhuyin course${state?.zhuyin?.all_symbols ? " (you know all 37 now, so nothing is shown)" : ""}.`}>
          <Seg value={settings.pinyin_support ? "on" : "off"} onChange={(v) => set({ pinyin_support: v === "on" })} options={[{ v: "on", l: "On" }, { v: "off", l: "Off" }]} />
        </Row>
        <Row label="Tone colours" hint="Tint each character by its tone. Off keeps the page monochrome.">
          <Seg value={settings.tone_colors ? "on" : "off"} onChange={(v) => set({ tone_colors: v === "on" })} options={[{ v: "off", l: "Off" }, { v: "on", l: "On" }]} />
        </Row>
        <Row label="Show Simplified" hint="Display the Simplified form in word look-ups while you make the switch.">
          <Seg value={settings.show_simplified ? "on" : "off"} onChange={(v) => set({ show_simplified: v === "on" })} options={[{ v: "on", l: "Show" }, { v: "off", l: "Hide" }]} />
        </Row>
        <Row label="Character typeface" hint="明體 is the print standard, 黑體 is what screens use, 楷體 shows handwritten stroke shapes.">
          <Seg value={settings.hanzi_font} onChange={(v) => set({ hanzi_font: v })} options={[{ v: "serif", l: <span className="zh">明體</span> }, { v: "sans", l: <span className="zh">黑體</span> }, { v: "kai", l: <span className="zh">楷體</span> }]} />
          <div className="han mt12" style={{ fontSize: 30 }}>那些年，我們一起追的女孩</div>
        </Row>
        <Row label="Appearance">
          <Seg value={settings.theme} onChange={(v) => set({ theme: v })} options={[{ v: "dark", l: "Black" }, { v: "light", l: "White" }]} />
        </Row>
        <Row label="Built-in zhuyin keyboard" hint="Type 注音 inside the app without installing anything. Turn it off to use your system input method.">
          <Seg value={settings.builtin_ime ? "on" : "off"} onChange={(v) => set({ builtin_ime: v === "on" })} options={[{ v: "on", l: "On" }, { v: "off", l: "System" }]} />
        </Row>
        <Row label="Voice" hint="Used for every audio button. The local voice is a Taiwanese speaker's voice generated on this computer; the Microsoft voices come from the cloud.">
          <div className="col gap12">
            <select className="field" style={{ maxWidth: 380 }} value={settings.tts_voice} onChange={(e) => { set({ tts_voice: e.target.value }); if (e.target.value === "local-breezy") api.post("/voice/start").then(() => refresh()).catch(() => {}); window.setTimeout(() => say("你好，我是你的台灣華語老師。"), 400); }}>
              {Object.entries(sv?.tts_voices || {}).map(([k, v]) => <option key={k} value={k}>{String(v)}</option>)}
            </select>
            {sv?.local_voice?.installed && (
              <div className="small muted">
                Local voice: {sv.local_voice.state}
                {sv.local_voice.state === "loading" && " — about half a minute; the Microsoft voice fills in until then"}
                {sv.local_voice.state === "ready" && " · each new sentence takes a second or two the first time, then plays instantly"}
                {sv.local_voice.error ? ` (${sv.local_voice.error})` : ""}
                {settings.tts_voice === "local-breezy" && sv.local_voice.state !== "ready" && (
                  <button className="btn ghost sm" style={{ height: 22 }} onClick={() => api.post("/voice/start").then(() => refresh())}>Check again</button>
                )}
              </div>
            )}
            <div className="row gap12">
              <span className="label">Speed</span>
              <Seg value={String(settings.tts_rate)} onChange={(v) => set({ tts_rate: parseInt(v, 10) })} options={[{ v: "-25", l: "Slow" }, { v: "-10", l: "Easy" }, { v: "0", l: "Natural" }, { v: "12", l: "Fast" }]} />
            </div>
          </div>
        </Row>
        <Row label="AI model" hint="Writes each day's lesson, runs the tutor and corrects your writing.">
          <ModelField value={settings.llm_model} onSave={(v) => set({ llm_model: v })} />
        </Row>
        <Row label="Services">
          <div className="col gap6 small">
            <div><span className="label">Tutor & lessons</span> {sv?.llm ? `connected · ${sv.llm_model}` : "no API key — set OPENAI_API_KEY in .env"}</div>
            <div><span className="label">Speech recognition</span> {sv?.whisper?.loaded ? `Whisper ${sv.whisper.model} on ${sv.whisper.device === "cuda" ? "GPU" : "CPU"}` : "loads on first use"}</div>
            <div><span className="label">Readings</span> {sv?.g2p?.loaded ? "context-aware Taiwan model" : sv?.g2p?.failed ? "dictionary fallback" : "loading"}</div>
          </div>
        </Row>
      </div>
    </div>
  );
}

function ModelField({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value);
  return (
    <div className="row gap12">
      <input className="field" style={{ maxWidth: 240 }} value={v} onChange={(e) => setV(e.target.value)} />
      <button className="btn sm" disabled={v === value || !v.trim()} onClick={() => onSave(v.trim())}>Save</button>
    </div>
  );
}
