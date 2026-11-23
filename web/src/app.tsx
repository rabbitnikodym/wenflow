import { PopupProvider } from "./han";
import { Progress, Settings } from "./pages/meta";
import { Read, Speak, Watch } from "./pages/media";
import { ReviewPage, Words, Zhuyin } from "./pages/study";
import { Today } from "./pages/today";
import { AppProvider, useApp, useRoute } from "./store";

const NAV = [
  { path: "", en: "Today", zh: "今日" },
  { path: "zhuyin", en: "Zhuyin", zh: "注音" },
  { path: "review", en: "Review", zh: "複習" },
  { path: "read", en: "Read", zh: "閱讀" },
  { path: "watch", en: "Watch", zh: "影片" },
  { path: "speak", en: "Speak", zh: "會話" },
  { path: "words", en: "Words", zh: "詞彙" },
  { path: "progress", en: "Progress", zh: "進度" },
  { path: "settings", en: "Settings", zh: "設定" },
];

function Shell() {
  const route = useRoute();
  const { state } = useApp();
  const top = route[0] || "";
  const sum = state?.summary;
  let page;
  switch (top) {
    case "": page = <Today />; break;
    case "day": page = <Today day={parseInt(route[1], 10) || undefined} key={route[1]} />; break;
    case "zhuyin": page = <Zhuyin route={route.slice(1)} />; break;
    case "review": page = <ReviewPage />; break;
    case "read": page = <Read route={route.slice(1)} />; break;
    case "watch": page = <Watch route={route.slice(1)} />; break;
    case "speak": page = <Speak route={route.slice(1)} />; break;
    case "words": page = <Words route={route.slice(1)} />; break;
    case "progress": page = <Progress />; break;
    case "settings": page = <Settings />; break;
    default: page = <Today />;
  }
  return (
    <div className="shell">
      <aside className="rail">
        <a className="brand" href="#/">
          <div className="mark">文流</div>
          <div className="word">Wenflow</div>
        </a>
        <nav className="nav">
          {NAV.map((n) => (
            <a key={n.path} href={`#/${n.path}`} className={top === n.path || (n.path === "" && top === "day") ? "on" : ""}>
              <span>
                {n.en}
                {n.path === "review" && (state?.srs?.due ?? 0) > 0 && <span className="dot num">{state?.srs?.due}</span>}
              </span>
              <span className="zh">{n.zh}</span>
            </a>
          ))}
        </nav>
        {sum && (
          <div className="rail-foot">
            <div>Day <b className="num">{Math.max(sum.day, 1)}</b> · Week <b className="num">{sum.week}</b></div>
            <div>Streak <b className="num">{sum.streak}</b></div>
            <div>Today <b className="num">{sum.minutes_today}</b> min</div>
          </div>
        )}
      </aside>
      <main className="main">{page}</main>
    </div>
  );
}

export function App() {
  return (
    <AppProvider>
      <PopupProvider>
        <Shell />
      </PopupProvider>
    </AppProvider>
  );
}
