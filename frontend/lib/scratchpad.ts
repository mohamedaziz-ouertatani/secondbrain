/**
 * The drawer scratchpad: one running Planner note per drawer that answers and fiches are clipped
 * into. Pure string logic here (tested with node's runner); the hook lives in useScratchpad.
 */

/** Each drawer's scratchpad is found by this title; "All drawers" keeps one with no course. */
export function scratchTitle(course: string | null): string {
  return course ? `Scratchpad · ${course}` : "Scratchpad";
}

/** A clip as a Markdown quote, crediting its call numbers on a last line. */
export function clipBlock(text: string, sources: string[]): string {
  const quoted = text
    .trim()
    .split("\n")
    .map((l) => (l.trim() ? `> ${l.trim()}` : ">"))
    .join("\n");
  const credit = [...new Set(sources)].join("; ");
  return credit ? `${quoted}\n>\n> — ${credit}` : quoted;
}

/** Appends a clip after whatever is there, one blank line apart. */
export function appendClip(body: string, clip: string): string {
  const head = body.replace(/\s+$/, "");
  return head ? `${head}\n\n${clip}\n` : `${clip}\n`;
}

type NoteLike = { title: string; course: string | null; kind: string; filed_path: string | null };

/** The drawer's live scratchpad: an unfiled note with its title. Filing one starts the next. */
export function pickScratch<T extends NoteLike>(items: T[], course: string | null): T | null {
  const title = scratchTitle(course);
  return items.find((i) => i.kind === "note" && !i.filed_path && i.course === course && i.title === title) ?? null;
}
