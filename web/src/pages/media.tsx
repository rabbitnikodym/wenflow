// Read (the novel, articles, news), Watch (videos) and Speak (tutor, pronunciation lab).
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Paragraph, Questions, ReadingBlock } from "../blocks/reading";
import { Conversation } from "../blocks/speak";
import { LEVEL_NAME, Player, VideoCard } from "../blocks/video";
import { RubySwitch, Reading as ReadingLine } from "../han";
import { ZhuyinInput } from "../ime";
import { ShadowLine } from "../speech";
import { go, useApp } from "../store";
import { Bar, Icon, Loading, useLoad } from "../ui";

// ---------------------------------------------------------------------------------------------
// Read
// ---------------------------------------------------------------------------------------------

export function Read({ route }: { route: string[] }) {
  if (route[0] === "chapter" && route[1]) return <ChapterReader id={parseInt(route[1], 10)} key={route[1]} />;
  if (route[0] === "article" && route[1]) return <ArticleReader id={parseInt(route[1], 10)} key={route[1]} />;
  return <Library />;
}

function Library() {
  const { refresh, toast } = useApp();
  const { data, reload } = useLoad(() => api.get("/library"), []);
  const news = useLoad(() => api.get("/news"), []);
  const [url, setUrl] = useState("");
  const [paste, setPaste] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [showPack, setShowPack] = useState(false);
  const [bookText, setBookText] = useState("");
  const [showPaste, setShowPaste] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  if (!data) return <div className="page"><Loading /></div>;
  const book = data.books.find((b: any) => b.active) || data.books[0];
  const pack = data.pack || {};

  const upload = async (f: File) => {
    setBusy("book");
    setErr("");
    try {
      const fd = new FormData();
      fd.append("file", f);
      await api.form("/books/upload", fd);
      await reload();
      refresh();
      toast("Book imported");
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy("");
  };
  const importText = async () => {
    setBusy("book");
    setErr("");
    try {
      await api.post("/books/text", { title: pack.title || "Book", author: pack.author || "", text: bookText });
      setBookText("");
      setShowPaste(false);
      await reload();
      refresh();
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy("");
  };
  const addArticle = async (u?: string) => {
    setBusy(u || "article");
    setErr("");
    try {
      const r = await api.post("/readings", u ? { url: u } : url.trim() ? { url: url.trim() } : { text: paste, title });
      go(`/read/article/${r.id}`);
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy("");
  };
  const nextChapter = book?.chapters.find((c: any) => (c.progress || 0) < 0.999);

  return (
    <div className="page">
      <div className="eyebrow">閱讀</div>
      <h1 className="display mt16">Read</h1>

      <div className="section mt32">
        <div className="row between top wrap gap24">
          <div>
            <div className="label">The novel</div>
            <div className="zh-display mt8" style={{ fontSize: 34, fontWeight: 900, lineHeight: 1.3 }}>{book?.title || pack.title}</div>
            <div className="muted mt4 zh">{book?.author || pack.author}{pack.year ? ` · ${pack.year}` : ""}</div>
          </div>
          {book && (
            <div className="row gap48">
              <div className="stat"><div className="v">{Math.round(book.progress * 100)}<small>%</small></div><div className="l">Read</div></div>
              {book.meta.stats && <div className="stat"><div className="v">{Math.round(book.meta.stats.coverage * 100)}<small>%</small></div><div className="l">Words known</div></div>}
              {book.meta.stats && <div className="stat"><div className="v">{book.meta.stats.teachable}</div><div className="l">Words to learn</div></div>}
            </div>
          )}
        </div>
        {pack.about && <p className="prose muted mt16">{pack.about}</p>}
        {book ? (
          <div className="mt24">
            <Bar value={book.progress} thick />
            <div className="row gap12 mt16 wrap">
              {nextChapter && <a className="btn primary" href={`#/read/chapter/${nextChapter.id}`}>Continue reading</a>}
              <a className="btn" href="#/words/book">Vocabulary for the book</a>
              <button className="btn ghost sm" onClick={async () => { if (confirm("Remove this book from the library? Your word cards stay.")) { await api.del(`/books/${book.id}`); reload(); refresh(); } }}>Remove</button>
            </div>
            {book.meta.converted && <p className="tiny faint mt12">This copy was in Simplified characters and has been converted to Traditional. A handful of characters may differ from the printed Taiwanese edition.</p>}
            <div className="list mt24" style={{ maxHeight: 420, overflow: "auto" }}>
              {book.chapters.map((c: any) => (
                <a key={c.id} className="item click" href={`#/read/chapter/${c.id}`}>
                  <span className="idx">{String(c.idx + 1).padStart(2, "0")}</span>
                  <span className="grow zh" style={{ fontSize: 18 }}>{c.title}</span>
                  <span className="tiny muted num">{c.chars.toLocaleString()} 字</span>
                  <span style={{ width: 90 }}><Bar value={c.progress || 0} /></span>
                </a>
              ))}
            </div>
          </div>
        ) : (
          <div className="panel mt24 col gap16">
            <div className="h2">Import your copy</div>
            <p className="small muted prose">
              The book itself is not bundled with the app. Add your own copy as an EPUB or text file (Traditional or Simplified — Simplified is converted), or paste the text.
              The app then splits it into chapters, works out which words you don't know yet, feeds them into your daily lessons in reading order, and serves the book a passage at a time.
            </p>
            <div className="row gap12 wrap">
              <input ref={file} type="file" accept=".epub,.txt,.text,.md" className="hide" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
              <button className="btn primary" disabled={busy === "book"} onClick={() => file.current?.click()}>{busy === "book" ? "Importing…" : "Choose EPUB or TXT"}</button>
              <button className="btn" onClick={() => setShowPaste((x) => !x)}>Paste text</button>
            </div>
            {showPaste && (
              <div className="col gap12">
                <textarea className="area" rows={6} style={{ fontSize: 16 }} placeholder="Paste the full text here…" value={bookText} onChange={(e) => setBookText(e.target.value)} />
                <div><button className="btn primary" disabled={bookText.length < 200 || busy === "book"} onClick={importText}>Import {bookText.length ? `${bookText.length.toLocaleString()} characters` : ""}</button></div>
              </div>
            )}
          </div>
        )}
        <div className="mt24">
          <button className="btn ghost sm" style={{ paddingLeft: 0 }} onClick={() => setShowPack((x) => !x)}>{showPack ? "Hide" : "Show"} the companion guide — characters, reading tips, {pack.culture_notes?.length || 0} culture notes</button>
          {showPack && (
            <div className="col gap32 mt16">
              {pack.characters?.length > 0 && (
                <div>
                  <div className="label mb8">Characters</div>
                  <div className="list">
                    {pack.characters.map((c: any) => (
                      <div key={c.name} className="item"><span className="zh" style={{ fontSize: 22, width: 110 }}>{c.name}</span><span className="muted small" style={{ width: 150 }}>{c.pinyin}</span><span className="small grow">{c.role}</span></div>
                    ))}
                  </div>
                </div>
              )}
              {pack.reading_tips?.length > 0 && (
                <div>
                  <div className="label mb8">Reading tips</div>
                  <ul className="prose small zh-ui" style={{ paddingLeft: 18, margin: 0 }}>{pack.reading_tips.map((t: string, i: number) => <li key={i} style={{ marginBottom: 6 }}>{t}</li>)}</ul>
                </div>
              )}
              <div className="grid2">
                {(pack.culture_notes || []).map((n: any) => (
                  <div key={n.title}><div className="h3 zh-ui">{n.title}</div><p className="small muted mt8 zh-ui" style={{ lineHeight: 1.75 }}>{n.body}</p></div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="section">
        <div className="row between base wrap gap16">
          <div className="h2">From Taiwan today</div>
          <button className="btn ghost sm" onClick={() => { news.setData(null); api.get("/news?refresh=true").then(news.setData); }}>Refresh</button>
        </div>
        {news.loading && !news.data ? <Loading label="Fetching headlines" /> : !news.data?.items?.length ? (
          <p className="muted small mt16">No headlines could be fetched right now.</p>
        ) : (
          <div className="list mt16">
            {news.data.items.slice(0, 18).map((it: any) => (
              <div key={it.url} className="item click" onClick={() => !busy && addArticle(it.url)}>
                <div className="grow">
                  <div className="zh" style={{ fontSize: 19, lineHeight: 1.5 }}>{it.title}</div>
                  <div className="tiny muted mt4">{it.source} · {it.category}</div>
                </div>
                <span className="chip">Level {it.level}</span>
                {busy === it.url ? <span className="spinner" /> : it.imported ? <span className="chip">Saved</span> : <span className="icon-btn">{Icon.right}</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="section">
        <div className="h2 mb16">Add something to read</div>
        <div className="grid2">
          <div className="col gap12">
            <div className="label">A link</div>
            <input className="field" placeholder="https://… any article in Chinese" value={url} onChange={(e) => setUrl(e.target.value)} />
            <div><button className="btn" disabled={!url.trim() || !!busy} onClick={() => addArticle()}>{busy === "article" ? "Importing…" : "Import"}</button></div>
          </div>
          <div className="col gap12">
            <div className="label">Or paste text</div>
            <input className="field" placeholder="Title (optional)" value={title} onChange={(e) => setTitle(e.target.value)} />
            <textarea className="field" rows={3} placeholder="Paste Chinese text — Simplified is converted to Traditional" value={paste} onChange={(e) => setPaste(e.target.value)} />
            <div><button className="btn" disabled={paste.trim().length < 10 || !!busy} onClick={() => addArticle()}>Add</button></div>
          </div>
        </div>
        {err && <div className="error mt12">{err}</div>}
      </div>

      {data.readings.length > 0 && (
        <div className="section">
          <div className="h2 mb16">Saved</div>
          <div className="list">
            {data.readings.map((r: any) => (
              <a key={r.id} className="item click" href={`#/read/article/${r.id}`}>
                <div className="grow">
                  <div className="zh" style={{ fontSize: 19 }}>{r.title}</div>
                  <div className="tiny muted mt4">{r.source} · {r.chars.toLocaleString()} 字 · {(r.created_at || "").slice(0, 10)}</div>
                </div>
                {r.coverage != null && <span className="chip">{Math.round(r.coverage * 100)}% known</span>}
                {r.read_at && <span className="chip solid">Read</span>}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ChapterReader({ id }: { id: number }) {
  const PAGE = 1400;
  const [start, setStart] = useState<number | null>(null);
  const [ch, setCh] = useState<any>(null);
  const [err, setErr] = useState("");
  const t0 = useRef(Date.now());

  useEffect(() => {
    // open where the reader left off
    api.get(`/chapters/${id}?start=0&length=1`).then((r) => {
      const s = r.progress >= 0.999 ? 0 : Math.round(r.progress * r.chars);
      setStart(s);
    }).catch((e) => setErr(e.message));
  }, [id]);
  useEffect(() => {
    if (start == null) return;
    setCh(null);
    t0.current = Date.now();
    api.get(`/chapters/${id}?start=${start}&length=${PAGE}`).then((r) => {
      setCh(r);
      window.scrollTo(0, 0);
    }).catch((e) => setErr(e.message));
  }, [id, start]);

  if (err) return <div className="page narrow"><div className="error">{err}</div></div>;
  if (!ch) return <div className="page"><Loading label="Opening the page" /></div>;
  const atEnd = ch.end >= ch.chars;
  const save = () => api.post(`/chapters/${id}/progress`, { end: ch.end, seconds: Math.min(900, Math.round((Date.now() - t0.current) / 1000)) }).catch(() => {});
  const next = async () => {
    await save();
    if (!atEnd) setStart(ch.end);
    else if (ch.next_id) go(`/read/chapter/${ch.next_id}`);
    else go("/read");
  };
  return (
    <div className="page narrow">
      <a className="btn ghost sm" href="#/read" style={{ paddingLeft: 0 }}>← Library</a>
      <div className="reader mt16">
        <div className="eyebrow zh">{ch.book_title}</div>
        <h1 className="zh" style={{ fontSize: 32, fontWeight: 700, marginTop: 8 }}>{ch.title}</h1>
        <div className="row gap16 mt12">
          <div className="grow"><Bar value={ch.end / ch.chars} /></div>
          <span className="tiny muted num">{Math.round((ch.end / ch.chars) * 100)}% of chapter</span>
        </div>
        <div className="toolbar mt16">
          <RubySwitch />
          <span className="tiny faint">Click a word to look it up</span>
        </div>
        {ch.start === 0 && ch.vocab?.length > 0 && <ChapterWords words={ch.vocab} />}
        <div className="mt24">
          {ch.paragraphs.map((p: any, i: number) => (
            <Paragraph key={`${ch.start}-${i}`} tokens={p} />
          ))}
        </div>
        <div className="row between mt32">
          <button className="btn" disabled={ch.start === 0 && !ch.prev_id} onClick={() => (ch.start > 0 ? setStart(Math.max(0, ch.start - PAGE)) : go(`/read/chapter/${ch.prev_id}`))}>← Back</button>
          <button className="btn primary lg" onClick={next}>{atEnd ? (ch.next_id ? "Next chapter" : "Finish") : "Next page"}</button>
        </div>
      </div>
    </div>
  );
}

function ChapterWords({ words }: { words: string[] }) {
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<any[] | null>(null);
  const { toast } = useApp();
  const load = async () => {
    setOpen((x) => !x);
    if (!info) {
      const out: any[] = [];
      for (const w of words.slice(0, 24)) out.push((await api.get(`/dict?w=${encodeURIComponent(w)}`)).info);
      setInfo(out);
    }
  };
  return (
    <div className="mt16">
      <button className="btn ghost sm" style={{ paddingLeft: 0 }} onClick={load}>{open ? "Hide" : "Preview"} {words.length} new words in this chapter</button>
      {open && (
        !info ? <div className="muted small">Loading…</div> : (
          <div className="row wrap gap24 mt12">
            {info.map((w: any) => (
              <div key={w.trad} className="col gap4" style={{ width: 170, cursor: "pointer" }} title="Add to review" onClick={async () => { await api.post("/srs/add", { word: w.trad, source: "book" }); toast(`${w.trad} added`); }}>
                <div className="row gap8 base"><span className="han" style={{ fontSize: 22 }}>{w.trad}</span><span className="tiny"><ReadingLine zhuyin={w.zhuyin} pinyin={w.pinyin} lean /></span></div>
                <div className="tiny muted">{(w.en || "").slice(0, 54)}</div>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}

function ArticleReader({ id }: { id: number }) {
  const { data, error, setData } = useLoad(() => api.get(`/readings/${id}`), [id]);
  const [busy, setBusy] = useState(false);
  const [score, setScore] = useState<number | null>(null);
  const t0 = useRef(Date.now());
  if (error) return <div className="page narrow"><div className="error">{error}</div></div>;
  if (!data) return <div className="page"><Loading label="Annotating" /></div>;
  const finish = (d?: any) => {
    api.post(`/readings/${id}/read`, { seconds: Math.min(1200, Math.round((Date.now() - t0.current) / 1000)) }).catch(() => {});
    if (d?.score != null) setScore(d.score);
    else go("/read");
  };
  const makeQs = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/readings/${id}/questions`);
      setData({ ...data, questions: r.questions });
    } catch {
      /* ignore */
    }
    setBusy(false);
  };
  return (
    <div className="page narrow">
      <div className="row between">
        <a className="btn ghost sm" href="#/read" style={{ paddingLeft: 0 }}>← Library</a>
        <div className="row gap8">
          {!data.questions?.length && <button className="btn sm" onClick={makeQs} disabled={busy}>{busy ? "Writing questions…" : "Add comprehension questions"}</button>}
          <button className="btn ghost sm" onClick={async () => { await api.del(`/readings/${id}`); go("/read"); }}>Delete</button>
        </div>
      </div>
      <div className="mt16">
        {score != null ? (
          <div className="col gap24 center" style={{ alignItems: "center", padding: "60px 0" }}>
            <div className="big-num">{Math.round(score * 100)}%</div>
            <a className="btn primary" href="#/read">Back to the library</a>
          </div>
        ) : (
          <ReadingBlock payload={data} onDone={finish} doneLabel="Mark as read" />
        )}
        {data.glossary?.unknown?.length > 0 && score == null && (
          <div className="reader mt32">
            <div className="label mb8">Words you may not know ({data.glossary.unknown.length}) · {Math.round((data.glossary.coverage || 0) * 100)}% of the text is familiar</div>
            <div className="zh muted" style={{ fontSize: 18, lineHeight: 2 }}>{data.glossary.unknown.slice(0, 60).join("　")}</div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Watch
// ---------------------------------------------------------------------------------------------

export function Watch({ route }: { route: string[] }) {
  if (route[0]) return <div><div className="stage-top" style={{ position: "sticky", top: 0, background: "var(--bg)", zIndex: 6 }}><a className="icon-btn" href="#/watch">{Icon.left}</a><div className="title">Watch<span className="zh">影片</span></div></div><Player videoId={route[0]} key={route[0]} /></div>;
  return <WatchHome />;
}

function WatchHome() {
  const lib = useLoad(() => api.get("/videos"), []);
  const [daily, setDaily] = useState<any>(null);
  const [finding, setFinding] = useState(false);
  const [url, setUrl] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const find = async (force = false) => {
    setFinding(true);
    setErr("");
    try {
      setDaily(await api.get(`/videos/daily${force ? "?force=true" : ""}`));
    } catch (e: any) {
      setErr(e.message);
    }
    setFinding(false);
  };
  useEffect(() => {
    find();
  }, []);

  const add = async () => {
    setBusy(true);
    setErr("");
    try {
      const r = await api.post("/videos/import", { url: url.trim() });
      go(`/watch/${r.video_id}`);
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy(false);
  };
  const upload = async (f: File) => {
    setBusy(true);
    setErr("");
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api.form("/videos/upload", fd);
      go(`/watch/${r.video_id}`);
    } catch (e: any) {
      setErr(e.message);
    }
    setBusy(false);
  };
  const todayIds = new Set((daily?.videos || []).map((v: any) => v.id));
  const others: any[] = (lib.data?.videos || []).filter((v: any) => !todayIds.has(v.id));
  const rest = others.filter((v) => v.ready || v.watched_at || v.source !== "discover");
  const older = others.filter((v) => !rest.includes(v));
  return (
    <div className="page wide">
      <div className="eyebrow">影片</div>
      <h1 className="display mt16">Watch</h1>
      <p className="prose muted mt16">
        Any YouTube video becomes a lesson: captions follow the speech, every word is clickable, and readings switch between 注音, pinyin and nothing.
        Videos without Chinese subtitles are transcribed on this computer.
      </p>
      <div className="section mt32">
        <div className="row between base wrap gap16 mb24">
          <div>
            <div className="h2">Today's picks</div>
            {daily && <div className="tiny muted mt4 upper">Aimed at: {LEVEL_NAME[daily.target_level]}</div>}
          </div>
          <button className="btn sm" onClick={() => find(true)} disabled={finding}>{finding ? "Looking…" : "Find more"}</button>
        </div>
        {!daily ? <Loading label="Looking for today's videos" /> : daily.videos.length === 0 ? (
          <p className="muted">Nothing could be fetched just now. Paste a link below, or try again in a moment.</p>
        ) : (
          <div className="grid4">
            {daily.videos.map((v: any) => <VideoCard key={v.id} v={v} onOpen={() => go(`/watch/${v.id}`)} />)}
          </div>
        )}
      </div>
      <div className="section">
        <div className="h2 mb16">Open any video</div>
        <div className="row gap16 wrap">
          <input className="field grow" style={{ maxWidth: 560 }} placeholder="Paste a YouTube link" value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && url.trim() && add()} />
          <button className="btn primary" disabled={!url.trim() || busy} onClick={add}>Open</button>
          <input ref={file} type="file" accept="video/*,audio/*" className="hide" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <button className="btn" disabled={busy} onClick={() => file.current?.click()}>Upload a file</button>
        </div>
        {err && <div className="error mt12">{err}</div>}
      </div>
      {rest.length > 0 && (
        <div className="section">
          <div className="h2 mb24">Your library</div>
          <div className="grid4">{rest.map((v: any) => <VideoCard key={v.id} v={v} onOpen={() => go(`/watch/${v.id}`)} />)}</div>
        </div>
      )}
      {older.length > 0 && (
        <div className="section">
          <div className="h2 mb24">Earlier suggestions</div>
          <div className="grid4">{older.slice(0, 16).map((v: any) => <VideoCard key={v.id} v={v} onOpen={() => go(`/watch/${v.id}`)} />)}</div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Speak
// ---------------------------------------------------------------------------------------------

export function Speak({ route }: { route: string[] }) {
  if (route[0] === "s" && route[1])
    return (
      <div className="page narrow">
        <a className="btn ghost sm" href="#/speak" style={{ paddingLeft: 0 }}>← Scenarios</a>
        <div className="mt24"><Conversation scenarioId={route[1]} twist={route[2] === "twist"} onDone={() => go("/speak")} key={route.join("/")} /></div>
      </div>
    );
  if (route[0] === "lab") return <Lab />;
  return <SpeakHome />;
}

function SpeakHome() {
  const { data } = useLoad(() => api.get("/tutor/scenarios"), []);
  const [level, setLevel] = useState(0);
  if (!data) return <div className="page"><Loading /></div>;
  const all: any[] = data.scenarios;
  const week = all.filter((s) => data.this_week.includes(s.id));
  const list = all.filter((s) => s.id !== "free" && (!level || s.level === level));
  return (
    <div className="page">
      <div className="eyebrow">會話</div>
      <h1 className="display mt16">Speak</h1>
      <p className="prose muted mt16">
        Talk with an AI partner who answers the way people in Taiwan do. After each turn you see what you said, which tones drifted, and how a local would have put it.
      </p>
      <div className="grid3 mt32">
        <a className="panel col gap8" href="#/speak/s/free">
          <div className="label">Open conversation</div>
          <div className="zh-display" style={{ fontSize: 30 }}>自由聊天</div>
          <div className="small muted">Chat about anything with 小安, a Taipei local.</div>
        </a>
        <a className="panel col gap8" href="#/speak/lab">
          <div className="label">Pronunciation lab</div>
          <div className="zh-display" style={{ fontSize: 30 }}>發音練習</div>
          <div className="small muted">Say any sentence and see your tones, syllable by syllable.</div>
        </a>
        <div className="panel flat col gap8">
          <div className="label">So far</div>
          <div className="mid-num">{data.history.length}</div>
          <div className="small muted">recent conversations</div>
        </div>
      </div>
      {week.length > 0 && (
        <div className="section mt32">
          <div className="h2 mb16">This week</div>
          <div className="grid3">
            {week.map((s) => <ScenarioCard key={s.id} s={s} />)}
          </div>
        </div>
      )}
      <div className="section">
        <div className="row between base wrap gap16 mb16">
          <div className="h2">All scenarios</div>
          <div className="row gap8">
            {[0, 1, 2, 3, 4, 5].map((l) => <button key={l} className={`btn sm ${level === l ? "on" : ""}`} onClick={() => setLevel(l)}>{l ? `L${l}` : "All"}</button>)}
          </div>
        </div>
        <div className="list">
          {list.map((s) => (
            <a key={s.id} className="item click" href={`#/speak/s/${s.id}`}>
              <span className="idx">L{s.level}</span>
              <div className="grow">
                <div className="row gap12 base"><span className="zh" style={{ fontSize: 21 }}>{s.title_zh}</span><span className="small muted">{s.title}</span></div>
                <div className="tiny faint mt4 zh-ui" style={{ display: "-webkit-box", WebkitLineClamp: 1, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{s.setting}</div>
              </div>
              {s.times > 0 && <span className="chip">{s.times}×</span>}
              <span className="icon-btn">{Icon.right}</span>
            </a>
          ))}
        </div>
      </div>
      {data.history.length > 0 && (
        <div className="section">
          <div className="h2 mb16">Recent</div>
          <div className="list">
            {data.history.map((h: any) => (
              <div key={h.id} className="item">
                <span className="tiny muted num" style={{ width: 96 }}>{(h.started_at || "").slice(0, 10)}</span>
                <span className="grow"><span className="zh" style={{ fontSize: 18 }}>{h.title_zh}</span> <span className="small muted">{h.title}</span></span>
                <span className="tiny muted num">{h.turns} turns</span>
                {h.report?.tone_graded > 0 && <span className="chip">{h.report.tone_slips} tone {h.report.tone_slips === 1 ? "slip" : "slips"}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ScenarioCard({ s }: { s: any }) {
  return (
    <a className="panel col gap8" href={`#/speak/s/${s.id}`}>
      <div className="label">Level {s.level}{s.times ? ` · done ${s.times}×` : ""}</div>
      <div className="zh-display" style={{ fontSize: 28, lineHeight: 1.3 }}>{s.title_zh}</div>
      <div className="small muted">{s.title}</div>
      <div className="tiny faint zh-ui" style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{s.setting}</div>
    </a>
  );
}

function Lab() {
  const [text, setText] = useState("");
  const [target, setTarget] = useState<any>(null);
  const random = async () => {
    const r = await api.get("/random-sentence");
    setTarget(r);
    setText(r.zh);
  };
  useEffect(() => {
    random();
  }, []);
  const use = async () => {
    const r = await api.post("/annotate", { text: text.trim(), gloss: false });
    setTarget({ zh: r.text, en: "", tokens: r.paragraphs[0] || [] });
  };
  return (
    <div className="page narrow">
      <a className="btn ghost sm" href="#/speak" style={{ paddingLeft: 0 }}>← Speak</a>
      <div className="eyebrow mt24">發音練習</div>
      <h1 className="h1 mt8">Pronunciation lab</h1>
      <p className="prose muted mt12">
        Listen to the Taiwanese model voice, say the sentence, and compare. The solid line in each box is the pitch you produced; the dashed line is the shape of the target tone.
      </p>
      <div className="col gap12 mt24">
        <ZhuyinInput value={text} onChange={setText} rows={2} placeholder="Type or paste a sentence to practise…" />
        <div className="row gap12">
          <button className="btn" onClick={use} disabled={!text.trim()}>Practise this sentence</button>
          <button className="btn ghost sm" onClick={random}>Random sentence</button>
        </div>
      </div>
      <hr className="mt32" />
      <div className="mt32">{target && <ShadowLine zh={target.zh} en={target.en} tokens={target.tokens} big />}</div>
    </div>
  );
}
