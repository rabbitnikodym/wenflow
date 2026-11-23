// App-wide state: settings, summary, and hash routing.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, setTtsVoice } from "./api";

export type Ruby = "zhuyin" | "pinyin" | "none";
export interface Settings {
  ruby: Ruby;
  pinyin_support: boolean;
  tone_colors: boolean;
  show_simplified: boolean;
  tts_voice: string;
  tts_rate: number;
  theme: "dark" | "light";
  builtin_ime: boolean;
  hanzi_font: "serif" | "sans" | "kai";
  llm_model: string;
}

export interface AppState {
  settings: Settings;
  summary: any;
  srs: any;
  services: any;
  book: any;
  zhuyin: { known: string; all_symbols: boolean; through: number; next: number | null; total: number; can_type: boolean; can_write: boolean; typing_from: number; writing_from: number };
}

interface Ctx {
  state: AppState | null;
  settings: Settings;
  set: (patch: Partial<Settings>) => void;
  refresh: () => Promise<void>;
  toast: (msg: string) => void;
}

const DEFAULTS: Settings = {
  ruby: "zhuyin", pinyin_support: true, tone_colors: false, show_simplified: true, tts_voice: "", tts_rate: 0, theme: "dark",
  builtin_ime: true, hanzi_font: "serif", llm_model: "",
};

const AppCtx = createContext<Ctx>({ state: null, settings: DEFAULTS, set: () => {}, refresh: async () => {}, toast: () => {} });
export const useApp = () => useContext(AppCtx);

export function AppProvider({ children }: { children: any }) {
  const [state, setState] = useState<AppState | null>(null);
  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [msg, setMsg] = useState("");

  const refresh = useCallback(async () => {
    const s = await api.get("/state");
    setState(s);
    setSettings(s.settings);
  }, []);

  useEffect(() => {
    refresh().catch(() => {});
  }, [refresh]);

  useEffect(() => {
    setTtsVoice(settings.tts_voice);
  }, [settings.tts_voice]);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = settings.theme;
    root.dataset.tones = settings.tone_colors ? "on" : "off";
    root.dataset.han = settings.hanzi_font;
  }, [settings.theme, settings.tone_colors, settings.hanzi_font]);

  const set = useCallback((patch: Partial<Settings>) => {
    setSettings((s) => ({ ...s, ...patch }));
    api.post("/settings", { values: patch }).catch(() => {});
  }, []);

  const toast = useCallback((m: string) => {
    setMsg(m);
    window.setTimeout(() => setMsg((cur) => (cur === m ? "" : cur)), 2200);
  }, []);

  return (
    <AppCtx.Provider value={{ state, settings, set, refresh, toast }}>
      {children}
      {msg && <div className="toast">{msg}</div>}
    </AppCtx.Provider>
  );
}

// ---- hash router ----
export function useRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const [parts, setParts] = useState<string[]>(read);
  useEffect(() => {
    const on = () => {
      setParts(read());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parts;
}

export const go = (path: string) => {
  window.location.hash = path.startsWith("/") ? path : `/${path}`;
};
