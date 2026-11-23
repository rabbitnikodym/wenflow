// Thin client for the Wenflow API.

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function handle(r: Response) {
  if (r.ok) return r.json();
  let msg = `${r.status} ${r.statusText}`;
  try {
    const j = await r.json();
    if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* not JSON */
  }
  throw new ApiError(msg, r.status);
}

export const api = {
  get: (path: string) => fetch(`/api${path}`).then(handle),
  post: (path: string, body?: any) =>
    fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    }).then(handle),
  del: (path: string) => fetch(`/api${path}`, { method: "DELETE" }).then(handle),
  form: (path: string, form: FormData) => fetch(`/api${path}`, { method: "POST", body: form }).then(handle),
  /** POST multipart and read a newline-delimited JSON stream, calling onEvent for each line. */
  async stream(path: string, form: FormData, onEvent: (ev: any) => void) {
    const r = await fetch(`/api${path}`, { method: "POST", body: form });
    if (!r.ok || !r.body) throw new ApiError(`${r.status} ${r.statusText}`, r.status);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) onEvent(JSON.parse(line));
      }
    }
    if (buf.trim()) onEvent(JSON.parse(buf));
  },
};

// `v` changes whenever the way speech is produced changes, so browsers drop clips they cached earlier.
const TTS_VERSION = 3;
let ttsVoice = "";
/** The voice chosen in Settings. Part of every audio URL, so each voice has its own cached clips. */
export const setTtsVoice = (voice: string) => {
  ttsVoice = voice || "";
};
export const ttsUrl = (text: string, rate?: number) =>
  `/api/tts?text=${encodeURIComponent(text)}${rate != null ? `&rate=${rate}` : ""}` +
  `${ttsVoice ? `&voice=${encodeURIComponent(ttsVoice)}` : ""}&v=${TTS_VERSION}`;
