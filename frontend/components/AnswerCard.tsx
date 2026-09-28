"use client";

import { ThumbsDown, ThumbsUp, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { AnswerProse } from "@/components/Prose";
import type { Citation } from "@/lib/api";
import { tintVar } from "@/lib/modules";

export type Entry = {
  id: string;
  /** query_log id; set once the answer is saved, so it can be deleted. */
  logId?: number;
  question: string;
  course: string | null;
  text: string;
  status: "searching" | "writing" | "done" | "error";
  citations: Citation[];
  valid: boolean | null;
  startedAt: number;
  endedAt?: number;
  error?: string;
  /** your rating of the answer; labelled answers feed the evaluation */
  feedback?: -1 | 1 | null;
  /** fiches marked relevant (true) or not (false), by citation number */
  relevant?: Record<string, boolean>;
};

/**
 * Mid-stream, a lone "-" (or "1.", "=") on the last line turns the line above into a setext heading
 * until the item's text arrives, so the card would flash a bold heading and reflow. Hold it back.
 */
function withoutDanglingMarker(text: string): string {
  return text.replace(/\n[ \t]*(?:[-*+=_]+|\d+[.)]?)[ \t]*$/, "");
}

/** Live elapsed seconds while an answer is in flight: the model can be slow, so say so. */
function useElapsed(entry: Entry): number {
  const [now, setNow] = useState(() => Date.now());
  const live = entry.status === "searching" || entry.status === "writing";
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [live]);
  return Math.max(0, Math.round(((entry.endedAt ?? (live ? now : entry.startedAt)) - entry.startedAt) / 1000));
}

function Stamp({ entry }: { entry: Entry }) {
  const s = useElapsed(entry);
  if (entry.status === "searching") return <span className="stamp live">Searching your fiches · {s} s</span>;
  if (entry.status === "writing") return <span className="stamp live">Writing · {s} s</span>;
  if (entry.status === "error") return <span className="stamp bad">Failed</span>;
  if (entry.citations.length === 0 && entry.valid === null)
    return <span className="stamp muted">Not in your fiches</span>;
  return <span className="stamp muted">Answered in {s} s</span>;
}

export function AnswerCard({
  entry,
  activeCite,
  onActiveCite,
  onPull,
  onDelete,
  onRate,
  labelError,
}: {
  entry: Entry;
  activeCite: number | null;
  onActiveCite: (n: number | null) => void;
  onPull: (n: number) => void;
  onDelete?: () => void;
  /** rate the answer: 1 good, -1 wrong, null to clear (pressing the active one again) */
  onRate?: (v: -1 | 1 | null) => void;
  labelError?: string | null;
}) {
  const known = new Set(entry.citations.map((c) => c.n));
  return (
    <article
      className="card answer"
      aria-busy={entry.status === "searching" || entry.status === "writing"}
      style={{ "--tint": tintVar(entry.course) } as React.CSSProperties}
    >
      <header className="card-head">
        <h2 className="question" dir="auto">
          {entry.question}
        </h2>
        <p className="card-meta">
          <span>{entry.course ?? "All drawers"}</span>
          <Stamp entry={entry} />
          {onRate && entry.status === "done" && (
            <span className="rate" role="group" aria-label="Rate this answer">
              <button
                type="button"
                className="icon-btn"
                aria-pressed={entry.feedback === 1}
                aria-label="Good answer"
                title="Good answer"
                onClick={() => onRate(entry.feedback === 1 ? null : 1)}
              >
                <ThumbsUp size={14} aria-hidden />
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-pressed={entry.feedback === -1}
                aria-label="Wrong answer"
                title="Wrong answer"
                onClick={() => onRate(entry.feedback === -1 ? null : -1)}
              >
                <ThumbsDown size={14} aria-hidden />
              </button>
            </span>
          )}
          {onDelete && (
            <button type="button" className="icon-btn delete" onClick={onDelete} aria-label="Delete this answer">
              <Trash2 size={14} aria-hidden />
            </button>
          )}
        </p>
      </header>

      <div className="card-body" dir="auto">
        {entry.status === "searching" && !entry.text ? (
          <div className="skeleton" aria-hidden>
            <span />
            <span />
            <span />
          </div>
        ) : (
          <AnswerProse
            text={entry.status === "writing" ? withoutDanglingMarker(entry.text) : entry.text}
            cite={{ known, active: activeCite, onActive: onActiveCite, onPull }}
          />
        )}
        {entry.status === "writing" && <span className="caret" aria-hidden />}
      </div>

      {entry.status === "error" && <p className="notice bad">{entry.error}</p>}
      {labelError && <p className="notice bad">{labelError}</p>}
      {entry.status === "done" && entry.valid === false && (
        <p className="notice">
          This answer doesn&apos;t cite your fiches properly. Check it against the sources before relying on it.
        </p>
      )}
    </article>
  );
}

/** A past card, receded: question only; click to bring it back to the front. */
export function PastCard({
  entry,
  depth,
  onOpen,
  onDelete,
}: {
  entry: Entry;
  depth: number;
  onOpen: () => void;
  onDelete?: () => void;
}) {
  return (
    <div className="card past" style={{ "--tint": tintVar(entry.course), "--depth": depth } as React.CSSProperties}>
      <button type="button" className="past-open" onClick={onOpen}>
        <span className="question" dir="auto">
          {entry.question}
        </span>
        <span className="past-meta">
          {entry.course ?? "All drawers"}
          {entry.citations.length ? ` · ${entry.citations.length} fiche${entry.citations.length > 1 ? "s" : ""}` : ""}
        </span>
      </button>
      {onDelete && (
        <button type="button" className="icon-btn delete" onClick={onDelete} aria-label={`Delete “${entry.question}”`}>
          <Trash2 size={14} aria-hidden />
        </button>
      )}
    </div>
  );
}
