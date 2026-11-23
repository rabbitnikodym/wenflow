// Zhuyin course, free review, and the vocabulary reference.
import { useMemo, useState } from "react";
import { api } from "../api";
import { Review } from "../blocks/review";
import { TypingDrill, TypingResult, ZhuyinUnit } from "../blocks/zhuyin";
import { Keyboard } from "../ime";
import { go, useApp } from "../store";
import { Icon, Loading, Speak, say, saySymbol, useLoad } from "../ui";

// ---------------------------------------------------------------------------------------------
// Zhuyin
// ---------------------------------------------------------------------------------------------

export function Zhuyin({ route }: { route: string[] }) {
  const { data, reload } = useLoad(() => api.get("/zhuyin"), []);
  const [tab, setTab] = useState<"course" | "chart" | "practice" | "setup">("course");
  const [picked, setPicked] = useState<any>(null);

  if (route[0] === "unit" && route[1])
    return (
      <div className="page narrow">
        <a className="btn ghost sm" href="#/zhuyin" style={{ paddingLeft: 0 }}>← All units</a>
        <div className="mt24">
          <ZhuyinUnit unit={parseInt(route[1], 10)} onDone={() => { reload(); go("/zhuyin"); }} />
        </div>
      </div>
    );
  if (!data) return <div className="page"><Loading /></div>;
  const doneCount = data.units.filter((u: any) => u.done).length;
  return (
    <div className="page">
      <div className="eyebrow">注音符號</div>
      <h1 className="display mt16">Zhuyin</h1>
      <p className="prose muted mt16">
        Thirty-seven symbols, four tone marks, one keyboard. Twenty-two short units take you from ㄅㄆㄇㄈ to typing full sentences the way people in Taiwan do.
      </p>
      <div className="row gap48 mt32 mb24">
        <div className="stat"><div className="v">{doneCount}<small>/ {data.units.length}</small></div><div className="l">Units done</div></div>
      </div>
      <div className="tabs">
        {/* tapping a symbol anywhere on this page plays its name: bo po mo fo, de te ne le … */}
        {([["course", "Course", "課程"], ["chart", "Chart", "符號表"], ["practice", "Typing practice", "打字"], ["setup", "Set up your devices", "安裝"]] as const).map(([k, en, zh]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k as any)}>{en}<span className="zh">{zh}</span></button>
        ))}
      </div>
      {tab === "course" && (
        <div className="list">
          {data.units.map((u: any) => (
            <a key={u.n} className="item click" href={`#/zhuyin/unit/${u.n}`}>
              <span className="idx">{String(u.n).padStart(2, "0")}</span>
              <div className="grow">
                <div className="h3">{u.title} <span className="zh muted" style={{ marginLeft: 10 }}>{u.title_zh}</span></div>
                <div className="small muted">{u.goal}</div>
              </div>
              <span className="zy muted" style={{ fontSize: 20 }}>{u.new.join("")}</span>
              <span className="chip" style={{ visibility: u.done ? "visible" : "hidden" }}>Done</span>
            </a>
          ))}
        </div>
      )}
      {tab === "chart" && (
        <div className="col gap32">
          {([["initials", "Initials 聲母"], ["medials", "Medials 介音"], ["finals", "Finals 韻母"]] as const).map(([k, title]) => (
            <div key={k}>
              <div className="h2 mb16">{title}</div>
              <div className="sym-grid">
                {data.symbols[k].map((s: any) => (
                  <div key={s.sym} className={`sym ${picked?.sym === s.sym ? "new" : ""}`} onClick={() => { setPicked(s); saySymbol(s.sym); }} title={`Hear its name: ${s.name}`}>
                    <div className="g">{s.sym}</div>
                    <div className="p">{s.pinyin}</div>
                    <div className="k">{s.key}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {picked && (
            <div className="panel row gap24 wrap">
              <div className="bigsym" style={{ fontSize: 80 }}>{picked.sym}</div>
              <div className="col gap8">
                <div>pinyin <b>{picked.pinyin}</b> · named <b>{picked.name}</b> · key <span className="kbd">{picked.key.toUpperCase()}</span></div>
                <div className="row gap8">
                  <button className="btn sm" onClick={() => saySymbol(picked.sym)}>Hear “{picked.name}”</button>
                  <button className="btn sm" onClick={() => say(picked.ex)}><span className="zh" style={{ fontSize: 14, letterSpacing: ".08em" }}>{picked.ex}</span> {picked.ex_py}</button>
                </div>
                <div className="small muted">{picked.hint}</div>
              </div>
            </div>
          )}
          <div>
            <div className="h2 mb16">Tones 聲調</div>
            <table className="t" style={{ maxWidth: 520 }}>
              <thead><tr><th>Tone</th><th>Mark</th><th>Key</th><th>Example</th></tr></thead>
              <tbody>
                {data.tones.map((t: any) => (
                  <tr key={t.name}><td>{t.name}</td><td className="zy" style={{ fontSize: 22 }}>{t.mark || "—"}</td><td><span className="kbd">{t.key}</span></td><td className="zh" style={{ fontSize: 18 }}>{t.ex}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <div className="h2 mb16">Compound finals 結合韻</div>
            <div className="sym-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))" }}>
              {data.compounds.map((c: any) => (
                <div key={c.zy} className="sym" onClick={() => say(c.sound)} title="Hear the sound">
                  <div className="g" style={{ fontSize: 26 }}>{c.zy}</div>
                  <div className="p">{c.pinyin}</div>
                  <div className="p zh">{c.ex}</div>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="h2 mb16">大千 keyboard</div>
            <Keyboard next={picked ? [picked.key] : []} />
            <p className="small muted prose mt16">The chart runs down the keyboard column by column: 1QAZ ㄅㄆㄇㄈ, 2WSX ㄉㄊㄋㄌ, EDC ㄍㄎㄏ, RFV ㄐㄑㄒ, 5TGB ㄓㄔㄕㄖ, YHN ㄗㄘㄙ, UJM ㄧㄨㄩ, 8IK, ㄚㄛㄜㄝ, 9OL. ㄞㄟㄠㄡ, 0P;/ ㄢㄣㄤㄥ and − for ㄦ.</p>
          </div>
        </div>
      )}
      {tab === "practice" && <Practice />}
      {tab === "setup" && <SetupGuide />}
    </div>
  );
}

function Practice() {
  const [items, setItems] = useState<any[] | null>(null);
  const [result, setResult] = useState<any>(null);
  const start = async () => {
    setResult(null);
    setItems(await api.get("/typing/sentences?n=6"));
  };
  if (!items)
    return (
      <div className="col gap24">
        {result && <TypingResult d={result} />}
        <p className="prose muted">Six sentences drawn from words you have reviewed. The built-in keyboard converts your zhuyin to characters; press ↓ to choose a different character and Enter to commit.</p>
        <div><button className="btn primary lg" onClick={start}>{result ? "Another round" : "Start typing"}</button></div>
      </div>
    );
  return <div style={{ maxWidth: 880 }}><TypingDrill items={items} onDone={(d) => { setResult(d); setItems(null); }} /></div>;
}

function SetupGuide() {
  const rows = [
    ["Windows", "Settings → Time & language → Language & region → Add a language → 中文 (繁體, 台灣). This installs 微軟注音 (Microsoft Bopomofo). Switch input with Win + Space; Shift toggles Chinese / English. Keep the layout on 標準 (Standard), which is 大千."],
    ["macOS", "System Settings → Keyboard → Input Sources → Edit → + → Chinese, Traditional → 注音 (Zhuyin). Layout 標準. Switch with Ctrl + Space or the Globe key."],
    ["iPhone / iPad", "Settings → General → Keyboard → Keyboards → Add New Keyboard → Chinese, Traditional → 注音."],
    ["Android (Gboard)", "Gboard settings → Languages → Add keyboard → 中文（繁體）→ 注音. The phone layout is the chart laid out in rows."],
    ["Punctuation on a PC", "In 微軟注音: Ctrl + , gives ，  Ctrl + . gives 。  Shift + / gives ？  Shift + 1 gives ！  The built-in keyboard in this app accepts the same keys plus ' for 、 and [ ] for 「」."],
  ];
  return (
    <div className="list" style={{ maxWidth: 820 }}>
      {rows.map(([h, b]) => (
        <div key={h} className="item top"><div className="h2" style={{ width: 190, flex: "none", paddingTop: 3 }}>{h}</div><p className="prose zh-ui">{b}</p></div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Review
// ---------------------------------------------------------------------------------------------

export function ReviewPage() {
  const { state } = useApp();
  const [run, setRun] = useState(0);
  const [kinds, setKinds] = useState("");
  const [active, setActive] = useState(false);
  const srs = state?.srs;
  return (
    <div className="page narrow">
      <div className="eyebrow">間隔複習</div>
      <h1 className="display mt16">Review</h1>
      <div className="row gap48 mt32 mb24">
        <div className="stat"><div className="v">{srs?.due ?? 0}</div><div className="l">Due now</div></div>
        <div className="stat"><div className="v">{srs?.total ?? 0}</div><div className="l">Cards</div></div>
        <div className="stat"><div className="v">{srs?.mature ?? 0}</div><div className="l">Mature</div></div>
      </div>
      {!active ? (
        <div className="col gap24">
          <p className="prose muted">
            Words come back just before you would forget them. Traditional characters are written by hand; Taiwan vocabulary is sometimes asked from the mainland word.
          </p>
          <div className="row gap8 wrap">
            {[["", "Everything"], ["word", "Words"], ["char", "Characters"], ["pron", "Readings"], ["sentence", "Sentences"]].map(([k, l]) => (
              <button key={k} className={`btn sm ${kinds === k ? "on" : ""}`} onClick={() => setKinds(k)}>{l}</button>
            ))}
          </div>
          <div><button className="btn primary lg" onClick={() => { setRun((r) => r + 1); setActive(true); }}>Start review</button></div>
        </div>
      ) : (
        <Review key={run} limit={60} kinds={kinds} onDone={() => setActive(false)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// Words: Taiwan vocabulary, readings, grammar, Traditional reference, the novel, my cards
// ---------------------------------------------------------------------------------------------

type WTab = "taiwan" | "pron" | "grammar" | "bridge" | "book" | "cards";

export function Words({ route }: { route: string[] }) {
  const tab = (route[0] as WTab) || "taiwan";
  const tabs: [WTab, string, string][] = [
    ["taiwan", "Taiwan words", "台灣用語"], ["pron", "Readings", "讀音"], ["grammar", "Grammar", "語法"],
    ["bridge", "Traditional", "繁體字"], ["book", "The novel", "那些年"], ["cards", "My cards", "卡片"],
  ];
  return (
    <div className="page wide">
      <div className="eyebrow">詞彙</div>
      <h1 className="display mt16">Words</h1>
      <div className="tabs mt32">
        {tabs.map(([k, en, zh]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => go(`/words/${k}`)}>{en}<span className="zh">{zh}</span></button>
        ))}
      </div>
      {tab === "taiwan" && <TaiwanTab />}
      {tab === "pron" && <PronTab />}
      {tab === "grammar" && <GrammarTab />}
      {tab === "bridge" && <BridgeTab />}
      {tab === "book" && <BookTab />}
      {tab === "cards" && <CardsTab />}
    </div>
  );
}

function AddBtn({ word, learning }: { word: string; learning?: boolean }) {
  const { toast } = useApp();
  const [added, setAdded] = useState(!!learning);
  if (added) return <span className="chip">In review</span>;
  return (
    <button className="icon-btn" title="Add to review" onClick={async () => { await api.post("/srs/add", { word, source: "manual" }); setAdded(true); toast("Added to review"); }}>
      {Icon.plus}
    </button>
  );
}

function TaiwanTab() {
  const { data } = useLoad(() => api.get("/vocab/taiwan"), []);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [reg, setReg] = useState("");
  const [n, setN] = useState(80);
  const items = useMemo(() => {
    if (!data) return [];
    const s = q.trim().toLowerCase();
    return data.items.filter((x: any) =>
      (!cat || x.category === cat) && (!reg || x.register === reg) &&
      (!s || x.trad.includes(s) || (x.mainland || "").includes(s) || (x.en || "").toLowerCase().includes(s) || (x.pinyin || "").replace(/\s/g, "").includes(s.replace(/\s/g, ""))));
  }, [data, q, cat, reg]);
  if (!data) return <Loading />;
  const regs = Array.from(new Set(data.items.map((x: any) => x.register))).filter(Boolean) as string[];
  return (
    <div className="col gap24">
      <div className="row gap24 wrap">
        <input className="field" style={{ maxWidth: 320 }} placeholder="Search 計程車, taxi, 出租车…" value={q} onChange={(e) => { setQ(e.target.value); setN(80); }} />
        <select className="field" style={{ maxWidth: 200 }} value={cat} onChange={(e) => setCat(e.target.value)}>
          <option value="">All categories</option>
          {data.categories.map((c: string) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="field" style={{ maxWidth: 180 }} value={reg} onChange={(e) => setReg(e.target.value)}>
          <option value="">Any register</option>
          {regs.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <span className="small muted num">{items.length} of {data.items.length} curated · {data.extra} more from the dictionary feed into lessons</span>
      </div>
      <table className="t">
        <thead><tr><th>Taiwan</th><th>Reading</th><th>Meaning</th><th>Mainland</th><th>Notes</th><th /></tr></thead>
        <tbody>
          {items.slice(0, n).map((x: any) => (
            <tr key={x.trad}>
              <td className="zh" style={{ fontSize: 24, whiteSpace: "nowrap" }}>{x.trad}</td>
              <td style={{ whiteSpace: "nowrap" }}><div className="zy">{x.zhuyin}</div><div className="small muted">{x.pinyin}</div></td>
              <td style={{ maxWidth: 220 }}>{x.en}<div className="row gap6 mt4">{x.register && x.register !== "neutral" && <span className="chip">{x.register}</span>}<span className="chip">{x.category}</span></div></td>
              <td className="zh" style={{ fontSize: 18, whiteSpace: "nowrap" }}>{x.mainland || "—"}</td>
              <td className="small" style={{ maxWidth: 420 }}>
                {x.example?.zh && <div className="zh" style={{ fontSize: 16 }}>{x.example.zh} <span className="muted" style={{ fontFamily: "var(--latin)", fontSize: 12 }}>{x.example.en}</span></div>}
                {x.note && <div className="muted mt4">{x.note}</div>}
              </td>
              <td><div className="row gap4"><Speak text={x.example?.zh || x.trad} /><AddBtn word={x.trad} learning={x.learning} /></div></td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length > n && <div><button className="btn" onClick={() => setN(n + 150)}>Show more</button></div>}
    </div>
  );
}

function PronTab() {
  const { data } = useLoad(() => api.get("/vocab/pron"), []);
  const [q, setQ] = useState("");
  if (!data) return <Loading />;
  const items = data.items.filter((x: any) => !q || x.trad.includes(q) || (x.tw || "").includes(q) || (x.en || "").toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="col gap24">
      <div className="row gap24 wrap">
        <input className="field" style={{ maxWidth: 320 }} placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="small muted">{items.length} words read differently in Taiwan</span>
      </div>
      <table className="t">
        <thead><tr><th>Word</th><th>Taiwan</th><th>Mainland</th><th>Notes</th><th /></tr></thead>
        <tbody>
          {items.map((x: any) => (
            <tr key={x.trad}>
              <td className="zh" style={{ fontSize: 24, whiteSpace: "nowrap" }}>{x.trad}<div className="small muted" style={{ fontFamily: "var(--latin)" }}>{x.en}</div></td>
              <td style={{ whiteSpace: "nowrap" }}><div className="zy">{x.tw_zhuyin}</div><div>{x.tw}</div></td>
              <td className="strike" style={{ whiteSpace: "nowrap" }}>{x.cn || x.cn_word}</td>
              <td className="small muted" style={{ maxWidth: 480 }}>
                {x.note}
                {x.status && x.status !== "standard" && <div className="mt4"><span className="chip">{x.status}</span></div>}
                {x.example?.zh && <div className="zh mt4" style={{ fontSize: 16, color: "var(--text)" }}>{x.example.zh}</div>}
              </td>
              <td><Speak text={x.example?.zh || x.trad} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GrammarTab() {
  const { data } = useLoad(() => api.get("/vocab/grammar"), []);
  const [open, setOpen] = useState<string | null>(null);
  const [cat, setCat] = useState("");
  if (!data) return <Loading />;
  const cats = Array.from(new Set(data.items.map((g: any) => g.category).filter(Boolean))) as string[];
  const items = data.items.filter((g: any) => !cat || g.category === cat);
  return (
    <div className="col gap24">
      <div className="row gap8 wrap">
        <button className={`btn sm ${!cat ? "on" : ""}`} onClick={() => setCat("")}>All</button>
        {cats.map((c) => <button key={c} className={`btn sm ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}>{c}</button>)}
      </div>
      <div className="list">
        {items.map((g: any) => (
          <div key={g.id}>
            <div className="item click" onClick={() => setOpen(open === g.id ? null : g.id)}>
              <span className="idx">{g.id.replace("g-", "")}</span>
              <div className="grow">
                <div className="h3" style={{ fontWeight: 500 }}>{g.title || g.pattern}</div>
                {g.title && <div className="zh muted">{g.pattern}</div>}
              </div>
              {g.category && <span className="chip">{g.category}</span>}
              <span className="chip" style={{ visibility: g.done ? "visible" : "hidden" }}>Studied</span>
            </div>
            {open === g.id && (
              <div className="col gap16" style={{ padding: "4px 0 28px 54px", maxWidth: 820 }}>
                <p className="prose">{g.explanation}</p>
                {(g.contrast || g.taiwan_note) && <p className="prose muted small zh-ui">{g.contrast || g.taiwan_note}</p>}
                {(g.examples || []).map((ex: any, i: number) => (
                  <div key={i} className="row gap8 top">
                    <div className="grow"><div className="zh" style={{ fontSize: 20 }}>{ex.zh}</div><div className="small muted">{ex.en}</div></div>
                    <Speak text={ex.zh} />
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function BridgeTab() {
  const { data } = useLoad(() => api.get("/vocab/bridge"), []);
  if (!data) return <Loading />;
  return (
    <div className="col gap48">
      <div className="row gap48">
        <div className="stat"><div className="v">{data.learned}<small>/ {data.total}</small></div><div className="l">Characters introduced</div></div>
        <div className="stat"><div className="v">{data.ptr}<small>/ {data.units}</small></div><div className="l">Units</div></div>
      </div>
      <div>
        <div className="h2 mb16">Component families — one rule, hundreds of characters</div>
        <table className="t">
          <thead><tr><th>簡</th><th>繁</th><th>Examples</th><th>Rule</th></tr></thead>
          <tbody>
            {data.families.map((f: any) => (
              <tr key={f.simplified + f.traditional}>
                <td className="zh muted" style={{ fontSize: 30 }}>{f.simplified}</td>
                <td className="zh" style={{ fontSize: 30, fontWeight: 700 }}>{f.traditional}</td>
                <td className="zh" style={{ fontSize: 20, whiteSpace: "nowrap" }}>{f.examples.map((e: any) => e[1]).join("　")}</td>
                <td className="small muted" style={{ maxWidth: 440 }}>{f.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <div className="h2 mb16">One Simplified, several Traditional — the ones that trip people up</div>
        <table className="t">
          <thead><tr><th>簡</th><th>繁</th><th>How to choose</th></tr></thead>
          <tbody>
            {data.one_to_many.map((o: any) => (
              <tr key={o.s}>
                <td className="zh muted" style={{ fontSize: 30 }}>{o.s}</td>
                <td>
                  {o.options.map((x: any) => (
                    <div key={x.t} className="row gap12 base">
                      <span className="zh" style={{ fontSize: 26, fontWeight: 700 }}>{x.t}</span>
                      <span className="small">{x.meaning}</span>
                      <span className="zh muted">{(x.words || []).join("　")}</span>
                    </div>
                  ))}
                </td>
                <td className="small muted" style={{ maxWidth: 380 }}>{o.tip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <div className="h2 mb16">Variant forms you will see in Taiwan</div>
        <table className="t">
          <thead><tr><th>Common</th><th>Also</th><th>Notes</th></tr></thead>
          <tbody>
            {data.variants.map((v: any) => (
              <tr key={v.form}><td className="zh" style={{ fontSize: 26 }}>{v.form}</td><td className="zh muted" style={{ fontSize: 26 }}>{v.alt}</td><td className="small muted">{v.note}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BookTab() {
  const { data } = useLoad(() => api.get("/book/words"), []);
  const [cat, setCat] = useState("");
  if (!data) return <Loading />;
  const cats = Array.from(new Set(data.pack.map((x: any) => x.category))) as string[];
  const items = data.pack.filter((x: any) => !cat || x.category === cat);
  const learning = data.pack.filter((x: any) => x.learning).length;
  return (
    <div className="col gap24">
      <p className="prose muted">
        Vocabulary for 《那些年，我們一起追的女孩》: {data.pack.length} words chosen for the novel's world (school life, banter, romance, narration), {learning} already in your review.
        {data.mined_total > 0 ? ` A further ${data.mined_total} words were found in your imported copy and are taught in reading order.` : " Import the text in Read and the app adds every other word you do not know yet, in reading order."}
      </p>
      <div className="row gap8 wrap">
        <button className={`btn sm ${!cat ? "on" : ""}`} onClick={() => setCat("")}>All</button>
        {cats.map((c) => <button key={c} className={`btn sm ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}>{c}</button>)}
      </div>
      <table className="t">
        <thead><tr><th>Word</th><th>Reading</th><th>Meaning</th><th>Example</th><th /></tr></thead>
        <tbody>
          {items.slice(0, 250).map((x: any) => (
            <tr key={x.trad}>
              <td className="zh" style={{ fontSize: 24, whiteSpace: "nowrap" }}>{x.trad}</td>
              <td style={{ whiteSpace: "nowrap" }}><div className="zy">{x.zhuyin}</div><div className="small muted">{x.pinyin}</div></td>
              <td style={{ maxWidth: 240 }}>{x.en}{x.note && <div className="small muted mt4">{x.note}</div>}</td>
              <td className="small" style={{ maxWidth: 420 }}><div className="zh" style={{ fontSize: 16 }}>{x.example?.zh}</div><div className="muted">{x.example?.en}</div></td>
              <td><div className="row gap4"><Speak text={x.example?.zh || x.trad} /><AddBtn word={x.trad} learning={x.learning} /></div></td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.mined.length > 0 && (
        <div>
          <div className="h2 mb16">Coming up from your copy of the text</div>
          <div className="row wrap gap16">
            {data.mined.slice(0, 120).map((w: any) => (
              <span key={w.trad} className="zh" style={{ fontSize: 20 }} title={`${w.pinyin} — ${w.en}`}>{w.trad}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CardsTab() {
  const [kind, setKind] = useState("word");
  const [q, setQ] = useState("");
  const { data, reload } = useLoad(() => api.get(`/vocab/cards?kind=${kind}&q=${encodeURIComponent(q)}`), [kind, q]);
  return (
    <div className="col gap24">
      <div className="row gap16 wrap">
        {[["word", "Words"], ["char", "Characters"], ["pron", "Readings"], ["sentence", "Sentences"]].map(([k, l]) => (
          <button key={k} className={`btn sm ${kind === k ? "on" : ""}`} onClick={() => setKind(k)}>{l}</button>
        ))}
        <input className="field" style={{ maxWidth: 260 }} placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {!data ? <Loading /> : data.cards.length === 0 ? (
        <p className="muted">No cards yet. They are created by your daily lessons, and whenever you add a word from a text or video.</p>
      ) : (
        <table className="t">
          <thead><tr><th>Card</th><th>Details</th><th>Interval</th><th>Due</th><th /></tr></thead>
          <tbody>
            {data.cards.map((c: any) => (
              <tr key={c.id}>
                <td className="zh" style={{ fontSize: 22 }}>{c.key}</td>
                <td className="small muted" style={{ maxWidth: 420 }}>{c.data.en || c.data.tw || (c.data.words || []).join("　")}</td>
                <td className="small num">{c.reps === 0 ? "new" : c.interval < 1 ? "learning" : `${Math.round(c.interval)} d`}</td>
                <td className="small num muted">{(c.due || "").slice(0, 10)}</td>
                <td><button className="icon-btn" title="Delete card" onClick={async () => { await api.del(`/srs/card/${c.id}`); reload(); }}>{Icon.trash}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
