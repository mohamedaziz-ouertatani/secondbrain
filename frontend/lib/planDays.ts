/** Which local days a planner item covers. Pure (tested with node's runner). */

const pad = (n: number) => String(n).padStart(2, "0");
const MAX_DAYS = 366;

/** Local calendar day, "2026-10-02". */
export function dayKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * Every local day from the start through the last day the item reaches. The end is exclusive, so an
 * all-day span ending at midnight stops the day before; capped at a year.
 */
export function daysOf(i: { starts_at: string | null; ends_at: string | null }): string[] {
  if (!i.starts_at) return [];
  const start = new Date(i.starts_at);
  const end = i.ends_at ? new Date(i.ends_at) : null;
  const last = dayKey(end && end > start ? new Date(end.getTime() - 1) : start);
  const days: string[] = [];
  for (let d = new Date(start.getFullYear(), start.getMonth(), start.getDate()); days.length < MAX_DAYS; d.setDate(d.getDate() + 1)) {
    const k = dayKey(d);
    days.push(k);
    if (k >= last) break;
  }
  return days;
}
