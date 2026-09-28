import { chapterCode, moduleCode } from "./modules";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const PDF = "application/pdf";
export const PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation";
export const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export type Citation = {
  n: number;
  chunk_id: number;
  doc_id: number;
  title: string;
  page: number;
  label: string | null;
  course: string | null;
  mime: string;
  path: string;
  snippet: string;
  text: string;
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
  first_seen: string;
  chunk_count: number;
};

export type DocumentPages = Omit<DocumentRow, "chunk_count"> & {
  pages: { page: number; label: string | null; text: string }[];
};

export type Health = {
  ok: boolean;
  db: { ok: boolean; error?: string };
  ollama: { reachable: boolean; llm_model?: string; llm_pulled?: boolean; embed_pulled?: boolean; error?: string };
};

type Locatable = { mime: string; page: number; label?: string | null };

/** Where in the file: "p. 3", "slide 3", a Word section heading, or "note". */
export function locator(c: Locatable): string {
  if (c.mime === PDF) return `p. ${c.page}`;
  if (c.mime === PPTX) return `slide ${c.page}`;
  return c.label ?? "note";
}

/** Library call number: PROB2 · CH1 · p. 3 */
export function callNumber(c: Locatable & { course: string | null; path: string }): string {
  const parts = [moduleCode(c.course), chapterCode(c.path)];
  if (c.mime === PDF || c.mime === PPTX || (c.mime === DOCX && c.label)) parts.push(locator(c));
  return parts.filter(Boolean).join(" · ");
}

/** "12 pages", "30 slides", "4 sections"; null for single-part notes. */
export function partsCount(mime: string, n: number): string | null {
  const unit = mime === PDF ? "page" : mime === PPTX ? "slide" : mime === DOCX ? "section" : null;
  return unit && `${n} ${unit}${n === 1 ? "" : "s"}`;
}

export function kindOf(mime: string): string {
  if (mime === PDF) return "PDF";
  if (mime === PPTX) return "Slides";
  if (mime === DOCX) return "Word";
  return "Note";
}

export function fileUrl(c: { doc_id: number; page?: number; mime: string }): string {
  const base = `${API_URL}/files/${c.doc_id}`;
  return c.mime === PDF && c.page ? `${base}#page=${c.page}` : base;
}

export function readerUrl(docId: number, page?: number): string {
  return `/documents/${docId}${page ? `#p-${page}` : ""}`;
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
    h.onError(`The backend answered ${res.status}. Check its log for the cause.`);
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
