"use client";

import { Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { UndoNote } from "@/components/UndoNote";
import { fetchHistory, type HistoryItem } from "@/lib/api";
import { dayLabel, openHref, useUndoDelete } from "@/lib/history";
import { moduleCode, tintVar } from "@/lib/modules";
import { useDrawer } from "@/lib/useLibrary";

const PAGE = 50;

/** One loaded list, tagged with the filter it answers, so a stale list is never shown for a new filter. */
type Loaded = { key: string; items: HistoryItem[]; more: boolean; error: boolean };

function firstLine(answer: string | null): string {
  if (answer === null) return "Failed before any answer arrived.";
  const line = answer.split("\n").find((l) => l.trim()) ?? "";
  return line.replace(/[#*_`>]|\[\d+\]/g, "").trim();
}

function HistoryView() {
  const drawer = useDrawer();
  const [query, setQuery] = useState("");
  const [q, setQ] = useState(""); // debounced
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const { hidden, remove, undo, pending, failed } = useUndoDelete();

  useEffect(() => {
    const t = window.setTimeout(() => setQ(query.trim()), 250);
    return () => window.clearTimeout(t);
  }, [query]);

  const key = `${drawer ?? ""}\u0000${q}`;
  useEffect(() => {
    const ctl = new AbortController();
    fetchHistory({ course: drawer, q, limit: PAGE }, ctl.signal)
      .then((rows) => setLoaded({ key, items: rows, more: rows.length === PAGE, error: false }))
      .catch((e) => {
        if (e?.name !== "AbortError") setLoaded({ key, items: [], more: false, error: true });
      });
    return () => ctl.abort();
  }, [drawer, q, key]);

  const current = loaded?.key === key ? loaded : null; // null while a new filter loads
  const items = current?.items ?? null;
  const more = current?.more ?? false;
  const error = current?.error ?? false;

  async function loadMore() {
    if (!current || !current.items.length) return;
    setLoadingMore(true);
    try {
      const rows = await fetchHistory({ course: drawer, q, before: current.items.at(-1)!.id, limit: PAGE });
      setLoaded({ ...current, items: [...current.items, ...rows], more: rows.length === PAGE });
    } catch {
      setLoaded({ ...current, error: true });
    } finally {
      setLoadingMore(false);
    }
  }

  const shown = (items ?? []).filter((h) => !hidden.has(h.id));
  const days: { label: string; rows: HistoryItem[] }[] = [];
  for (const h of shown) {
    const label = dayLabel(h.ts);
    if (days.at(-1)?.label !== label) days.push({ label, rows: [] });
    days.at(-1)!.rows.push(h);
  }

  return (
    <div className="drawer-view history-view">
      <header className="drawer-head">
        <h1>History</h1>
        <p>{drawer ? `Questions asked in ${drawer}` : "Every question you've asked, newest first"}</p>
      </header>

      <div className="drawer-tools">
        <label className="search">
          <Search size={16} aria-hidden />
          <span className="sr-only">Search questions and answers</span>
          <input
            type="search"
            dir="auto"
            value={query}
            placeholder="Search questions and answers…"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>

      {error && <p className="notice bad">Couldn&apos;t load your history. Is the backend running?</p>}
      {items === null && !error && <p className="muted">Pulling your old questions…</p>}
      {items !== null && !error && shown.length === 0 && (
        <p className="muted">
          {q ? `Nothing matches “${q}”.` : drawer ? `No questions asked in ${drawer} yet.` : "No questions asked yet."}
        </p>
      )}

      {days.map((d) => (
        <section key={d.label} className="history-day" aria-label={d.label}>
          <h2 className="stack-label">{d.label}</h2>
          <ol className="history-list">
            {d.rows.map((h) => (
              <li key={h.id} className="history-row" style={{ "--tint": tintVar(h.course) } as React.CSSProperties}>
                <Link href={openHref(h.id, drawer)} className="history-open">
                  <span className="callno">{h.course ? moduleCode(h.course) : "ALL"}</span>
                  <span className="question" dir="auto">
                    {h.question}
                  </span>
                  <span className="history-answer" dir="auto">
                    {firstLine(h.answer)}
                  </span>
                  <time dateTime={h.ts}>
                    {new Date(h.ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
                  </time>
                </Link>
                <button
                  type="button"
                  className="icon-btn delete"
                  onClick={() => remove(h.id)}
                  aria-label={`Delete “${h.question}”`}
                >
                  <Trash2 size={14} aria-hidden />
                </button>
              </li>
            ))}
          </ol>
        </section>
      ))}

      {more && (
        <button type="button" className="quiet-btn load-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load older questions"}
        </button>
      )}

      <UndoNote pending={pending} failed={failed} onUndo={undo} />
    </div>
  );
}

export default function HistoryPage() {
  return (
    <Suspense>
      <HistoryView />
    </Suspense>
  );
}
