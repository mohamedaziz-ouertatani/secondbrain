/**
 * Plain-language readings of admin numbers: each turns a value into a short sentence, or null when
 * there is nothing to read. Pure (tested with node's runner); `now` is always passed in.
 */
import type { AdminStatus } from "./api.ts";

export const DAY_MS = 86_400_000;
export const BACKUP_OLD_DAYS = 2;
export const SYNC_GRACE_DAYS = 2;
export const VRAM_FULL = 0.85;

export const percent = (n: number, of: number): number => Math.round((n / of) * 100);

export const daysSince = (iso: string, now: Date): number => (now.getTime() - new Date(iso).getTime()) / DAY_MS;

/** "just now", "30 min ago", "5 h ago", "3 days ago": the same steps as `ago` in seen.ts. */
export function age(iso: string, now: Date): string {
  const s = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 1.5) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

export const isBackupOld = (at: string | null, now: Date): boolean =>
  at === null || daysSince(at, now) > BACKUP_OLD_DAYS;

export const isSyncOld = (at: string | null, autoDays: number, now: Date): boolean =>
  at === null || daysSince(at, now) > autoDays + SYNC_GRACE_DAYS;

/** The first service that's down, in the order that blocks answers. */
export function servicesReading(s: AdminStatus["services"]): { ok: boolean; text: string } {
  if (!s) return { ok: false, text: "Couldn't check the services." };
  if (!s.db.ok) return { ok: false, text: "Database offline. Run docker compose up." };
  if (!s.ollama.reachable) return { ok: false, text: "Ollama isn't running. Start it from the tray or run ollama serve." };
  if (!s.ollama.llm_pulled || !s.ollama.embed_pulled)
    return { ok: false, text: "A model isn't pulled yet. See the README setup." };
  return { ok: true, text: "Database, Ollama and both models ready" };
}

export function recallReading(k: number, v: number | null | undefined): string | null {
  if (v === null || v === undefined) return null;
  const p = Math.round(v * 100);
  return k === 1
    ? `the right page comes first for ${p}% of questions`
    : `the right page is in the top ${k} for ${p}% of questions`;
}

export function gpuShareReading(share: number | null | undefined): string | null {
  if (share === null || share === undefined) return null;
  if (share >= 0.995) return "all on the GPU: full speed";
  if (share <= 0) return "all on the CPU, so answers are much slower";
  return `${Math.round(share * 100)}% on the GPU; the rest runs on the CPU, so answers are slower`;
}

export function vramReading(usedMib: number, totalMib: number): string | null {
  if (!(totalMib > 0)) return null;
  if (usedMib / totalMib >= VRAM_FULL) return "nearly full: a larger context window may push the model onto the CPU";
  return `${((totalMib - usedMib) / 1024).toFixed(1)} GB free`;
}

export function rateReading(n: number, of: number, noun: string): string {
  if (of === 0) return `no ${noun} yet`;
  return `${n} of ${of} ${noun} (${percent(n, of)}%)`;
}

export function indexReading(index: { documents: number; chunks: number; excluded: number } | null): string | null {
  if (!index) return null;
  const f = (n: number) => n.toLocaleString("en-GB");
  const excluded = index.excluded ? `${f(index.excluded)} excluded from answers` : "nothing excluded";
  return `${f(index.documents)} files · ${f(index.chunks)} passages · ${excluded}`;
}

/** What an ingest run did: "2 indexed, 5 already had". */
export const countsLine = (r: Record<string, number>): string =>
  Object.entries(r)
    .map(([k, n]) => `${n} ${k.replace("_", " ")}`)
    .join(", ") || "nothing to do";
