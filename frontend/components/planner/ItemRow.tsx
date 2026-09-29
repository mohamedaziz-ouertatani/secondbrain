"use client";

import { CalendarClock, StickyNote } from "lucide-react";
import { moduleCode, tintVar } from "@/lib/modules";
import { announce, isOverdue, type PlannerItem, patchItem, whenLabel } from "@/lib/planner";

function label(i: PlannerItem): string {
  return i.title || i.body.split("\n").find((l) => l.trim())?.trim() || "Untitled note";
}

/** One planner line: a checkbox for to-dos, the title, and a call number with module and time. */
export function ItemRow({ item, onOpen }: { item: PlannerItem; onOpen: (i: PlannerItem) => void }) {
  const done = !!item.done_at;
  const cls = ["plan-row", done && "done", item.removed_at && "removed", isOverdue(item) && "overdue"]
    .filter(Boolean)
    .join(" ");
  const meta = [item.course ? moduleCode(item.course) : null, whenLabel(item), item.source === "blackboard" ? "BLACKBOARD" : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className={cls} style={{ "--tint": tintVar(item.course) } as React.CSSProperties}>
      {item.kind === "todo" ? (
        <input
          type="checkbox"
          className="plan-check"
          checked={done}
          aria-label={done ? `Reopen “${label(item)}”` : `Mark “${label(item)}” done`}
          onChange={() => patchItem(item.id, { done: !done }).catch(announce)}
        />
      ) : item.kind === "event" ? (
        <CalendarClock size={15} className="plan-kind" aria-label="Event" />
      ) : (
        <StickyNote size={15} className="plan-kind" aria-label="Note" />
      )}
      <button type="button" className="plan-open" onClick={() => onOpen(item)}>
        <span className="plan-title" dir="auto">
          {label(item)}
        </span>
        {meta && <span className="callno">{meta}</span>}
        {item.removed_at && <span className="plan-flag">removed on Blackboard</span>}
      </button>
    </li>
  );
}
