export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Citation = {
  n: number;
  chunk_id: number;
  doc_id: number;
  title: string;
  page: number;
  label: string | null;
  course: string | null;
  mime: string;
  snippet: string;
};

export type Done = {
  answer: string;
  citations: Citation[];
  citation_valid: boolean | null;
  log_id: number | null;
};

export type DocumentRow = {
  id: number;
  path: string;
  title: string;
  course: string | null;
  mime: string;
  page_count: number;
  status: "ok" | "empty_text" | "error";
  error: string | null;
  ingested_at: string;
  chunk_count: number;
};

const PDF = "application/pdf";
const PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

/** Where in the file a citation points: "p. 3", "slide 3", a Word section heading, or "note". */
export function locator(c: Pick<Citation, "mime" | "page" | "label">): string {
  if (c.mime === PDF) return `p. ${c.page}`;
  if (c.mime === PPTX) return `slide ${c.page}`;
  return c.label ?? "note";
}

/** "12 pages", "30 slides", "4 sections" — null for single-part notes. */
export function partsCount(mime: string, n: number): string | null {
  const unit = mime === PDF ? "page" : mime === PPTX ? "slide" : mime === DOCX ? "section" : null;
  return unit && `${n} ${unit}${n === 1 ? "" : "s"}`;
}

export function fileUrl(c: Pick<Citation, "doc_id" | "page" | "mime">): string {
  const base = `${API_URL}/files/${c.doc_id}`;
  return c.mime === PDF ? `${base}#page=${c.page}` : base;
}

type Handlers = {
  onToken: (text: string) => void;
  onDone: (done: Done) => void;
  onError: (message: string) => void;
};

/** POST /ask and parse the SSE stream (EventSource can't POST). */
export async function askStream(question: string, course: string | null, h: Handlers, signal?: AbortSignal) {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, course }),
      signal,
    });
  } catch {
    h.onError(`Can't reach the backend at ${API_URL}. Start it with: uv run uvicorn app.main:app`);
    return;
  }
  if (!res.ok || !res.body) {
    h.onError(`The backend returned ${res.status}.`);
    return;
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!event || data === undefined) continue;
      const payload = JSON.parse(data);
      if (event === "token") h.onToken(payload.text);
      else if (event === "done") h.onDone(payload);
      else if (event === "error") h.onError(payload.message);
    }
  }
}

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} returned ${res.status}`);
  return res.json();
}
