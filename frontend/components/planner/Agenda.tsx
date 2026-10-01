"use client";

import { useEffect } from "react";
import { dayHeading, dayKey, daysOf, isOverdue, type PlannerItem } from "@/lib/planner";
import { ItemRow } from "./ItemRow";

/** Overdue first, then each day from today on; a span is listed under every day it covers. Past done items and notes aren't shown. */
export function Agenda({
  items,
  onOpen,
  focusDay,
}: {
  items: PlannerItem[];
  onOpen: (i: PlannerItem) => void;
  focusDay?: string | null;
}) {
  const now = new Date();
  const today = dayKey(now);
  const overdue = items.filter((i) => isOverdue(i, now));
  const days = new Map<string, PlannerItem[]>();
  for (const i of items) {
    if (i.kind === "note" || isOverdue(i, now)) continue;
    for (const k of daysOf(i)) if (k >= today) days.set(k, [...(days.get(k) ?? []), i]);
  }

  useEffect(() => {
    if (focusDay) document.getElementById(`day-${focusDay}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [focusDay]);

  if (!overdue.length && !days.size)
    return (
      <p className="muted plan-empty">
        Nothing coming up. Type a deadline above, or sync Blackboard to bring in its due dates.
      </p>
    );
  return (
    <div className="agenda">
      {overdue.length > 0 && (
        <section className="agenda-day overdue" aria-label="Overdue">
          <h3 className="stack-label">Overdue</h3>
          <ul className="plan-list">
            {overdue.map((i) => (
              <ItemRow key={i.id} item={i} onOpen={onOpen} />
            ))}
          </ul>
        </section>
      )}
      {[...days.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, rows]) => (
        <section key={k} id={`day-${k}`} className="agenda-day" aria-label={dayHeading(k)}>
          <h3 className="stack-label">{dayHeading(k)}</h3>
          <ul className="plan-list">
            {rows.map((i) => (
              <ItemRow key={i.id} item={i} onOpen={onOpen} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
