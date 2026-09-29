"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Entry } from "@/components/AnswerCard";
import { deleteHistory, type HistoryItem } from "./api";

export const UNDO_MS = 5000;

export function toEntry(h: HistoryItem): Entry {
  const ended = Date.parse(h.ts);
  return {
    id: String(h.id),
    logId: h.id,
    question: h.question,
    course: h.course,
    text: h.answer ?? "",
    status: h.answer === null ? "error" : "done",
    error: h.answer === null ? "This answer failed before any text arrived." : undefined,
    citations: h.citations,
    valid: h.citation_valid,
    startedAt: ended - (h.latency_ms ?? 0),
    endedAt: ended,
    feedback: h.feedback ?? null,
    relevant: h.labels?.relevant ?? {},
  };
}

/** The desk, opened on one past message, inside the same drawer. */
export function openHref(id: number, drawer: string | null): string {
  const p = new URLSearchParams();
  if (drawer) p.set("m", drawer);
  p.set("open", String(id));
  return `/?${p}`;
}

/** "Today", "Yesterday", else "12 Sep". */
export function dayLabel(ts: string, now = new Date()): string {
  const d = new Date(ts);
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/**
 * Delete with undo instead of a confirm dialog: the message hides at once and the DELETE is only
 * sent after UNDO_MS, on pagehide or on unmount. One pending delete at a time; a second one commits the first.
 */
export function useUndoDelete(del: (id: number) => Promise<boolean> = deleteHistory) {
  const [hidden, setHidden] = useState<ReadonlySet<number>>(new Set());
  const [pending, setPending] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const pendingRef = useRef<{ id: number; timer: number } | null>(null);

  const unhide = useCallback((id: number) => {
    setHidden((h) => {
      const next = new Set(h);
      next.delete(id);
      return next;
    });
  }, []);

  const commit = useCallback(() => {
    const p = pendingRef.current;
    if (!p) return;
    pendingRef.current = null;
    window.clearTimeout(p.timer);
    setPending(null);
    del(p.id).then((ok) => {
      if (!ok) {
        unhide(p.id);
        setFailed(true);
      }
    });
  }, [unhide, del]);

  const remove = useCallback(
    (id: number) => {
      commit();
      setFailed(false);
      setHidden((h) => new Set(h).add(id));
      pendingRef.current = { id, timer: window.setTimeout(commit, UNDO_MS) };
      setPending(id);
    },
    [commit],
  );

  const undo = useCallback(() => {
    const p = pendingRef.current;
    if (!p) return;
    pendingRef.current = null;
    window.clearTimeout(p.timer);
    setPending(null);
    unhide(p.id);
  }, [unhide]);

  useEffect(() => {
    window.addEventListener("pagehide", commit);
    return () => {
      window.removeEventListener("pagehide", commit);
      commit();
    };
  }, [commit]);

  return { hidden, remove, undo, pending, failed };
}
