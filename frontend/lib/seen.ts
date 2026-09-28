/** "New" marks: a document stays marked until opened. Per-browser convenience, so localStorage. */

const KEY = "sb.seen.v1";
const FIRST_VISIT = "sb.firstVisit.v1";

function read(): Set<number> {
  try {
    return new Set(JSON.parse(localStorage.getItem(KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

/** Anything ingested before the first visit is not "new": the whole library would be. */
function firstVisit(): number {
  try {
    const v = localStorage.getItem(FIRST_VISIT);
    if (v) return Number(v);
    const now = Date.now();
    localStorage.setItem(FIRST_VISIT, String(now));
    return now;
  } catch {
    return Date.now();
  }
}

export function isNew(doc: { id: number; first_seen: string }): boolean {
  return new Date(doc.first_seen).getTime() > firstVisit() && !read().has(doc.id);
}

/** "3 h ago", "2 days ago": when material last arrived. */
export function ago(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 1.5) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export function newestFiled(docs: { first_seen: string }[]): string | null {
  return docs.reduce<string | null>((m, d) => (!m || d.first_seen > m ? d.first_seen : m), null);
}

export function markSeen(id: number): void {
  try {
    const s = read();
    s.add(id);
    localStorage.setItem(KEY, JSON.stringify([...s]));
    window.dispatchEvent(new Event("sb:seen"));
  } catch {
    /* storage unavailable: marks just stay */
  }
}
