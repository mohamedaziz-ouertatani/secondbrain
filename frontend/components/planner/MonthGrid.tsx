"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { tintVar } from "@/lib/modules";
import { dayKey, type PlannerItem } from "@/lib/planner";

const WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MAX_CHIPS = 3;

/** Six Monday-first weeks around `month`; each day shows up to three chips, then "+N". */
export function MonthGrid({
  items,
  month,
  onMonth,
  onOpen,
  onDay,
}: {
  items: PlannerItem[];
  month: Date;
  onMonth: (m: Date) => void;
  onOpen: (i: PlannerItem) => void;
  onDay: (key: string) => void;
}) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const start = new Date(first);
  start.setDate(1 - ((first.getDay() + 6) % 7));
  const cells = Array.from({ length: 42 }, (_, n) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + n));
  const byDay = new Map<string, PlannerItem[]>();
  for (const i of items) {
    if (!i.starts_at || i.kind === "note") continue;
    const k = dayKey(new Date(i.starts_at));
    byDay.set(k, [...(byDay.get(k) ?? []), i]);
  }
  const today = dayKey(new Date());
  const shift = (n: number) => onMonth(new Date(month.getFullYear(), month.getMonth() + n, 1));

  return (
    <div className="month">
      <div className="month-head">
        <button type="button" className="icon-btn" onClick={() => shift(-1)} aria-label="Previous month">
          <ChevronLeft size={16} aria-hidden />
        </button>
        <h3>{month.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</h3>
        <button type="button" className="icon-btn" onClick={() => shift(1)} aria-label="Next month">
          <ChevronRight size={16} aria-hidden />
        </button>
      </div>
      <div className="month-grid">
        {WEEK.map((w) => (
          <div key={w} className="month-weekday" aria-hidden>
            {w}
          </div>
        ))}
        {cells.map((d) => {
          const k = dayKey(d);
          const rows = byDay.get(k) ?? [];
          const cls = ["month-cell", d.getMonth() !== month.getMonth() && "outside", k === today && "today"]
            .filter(Boolean)
            .join(" ");
          return (
            <div key={k} className={cls}>
              <button type="button" className="month-day" onClick={() => onDay(k)} aria-label={`Show ${k} in the agenda`}>
                {d.getDate()}
              </button>
              {rows.slice(0, MAX_CHIPS).map((i) => (
                <button
                  key={i.id}
                  type="button"
                  className={`month-chip${i.done_at || i.removed_at ? " done" : ""}`}
                  style={{ "--tint": tintVar(i.course) } as React.CSSProperties}
                  onClick={() => onOpen(i)}
                  title={i.title}
                >
                  {i.title}
                </button>
              ))}
              {rows.length > MAX_CHIPS && (
                <button type="button" className="month-more" onClick={() => onDay(k)}>
                  +{rows.length - MAX_CHIPS}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
