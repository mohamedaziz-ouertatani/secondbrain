"use client";

import { useCallback, useEffect, useState } from "react";
import { API_URL, type DocumentRow, getJSON, partsCount } from "@/lib/api";

const PROBLEM: Record<Exclude<DocumentRow["status"], "ok">, string> = {
  empty_text: "No text found. It looks like a scanned PDF, so it can't be searched yet.",
  error: "Couldn't be read",
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export default function DocumentsPage() {
  const [docs, setDocs] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  const load = useCallback(() => {
    getJSON<DocumentRow[]>("/documents")
      .then((d) => {
        setDocs(d);
        setError(null);
      })
      .catch(() => setError(`Can't reach the backend at ${API_URL}.`));
  }, []);

  useEffect(load, [load]);

  async function rescan() {
    setScanning(true);
    try {
      await fetch(`${API_URL}/ingest/rescan`, { method: "POST" });
    } catch {
      setError(`Can't reach the backend at ${API_URL}.`);
    } finally {
      setScanning(false);
      load();
    }
  }

  const groups = new Map<string, DocumentRow[]>();
  for (const d of docs ?? []) {
    const k = d.course ?? "Loose notes";
    groups.set(k, [...(groups.get(k) ?? []), d]);
  }

  return (
    <>
      <div className="lib-head">
        <h1>Library</h1>
        <button type="button" onClick={rescan} disabled={scanning}>
          {scanning ? "Rescanning…" : "Rescan inbox"}
        </button>
      </div>
      {error && <p className="notice error">{error}</p>}
      {docs?.length === 0 && (
        <p className="empty">
          Your library is empty. Put files in <code>inbox/&lt;course&gt;/</code> and they&apos;ll be added
          automatically.
        </p>
      )}
      {[...groups].map(([course, rows]) => (
        <section key={course} className="course">
          <h2>{course}</h2>
          <ul className="docs">
            {rows.map((d) => (
              <li key={d.id}>
                <a href={`${API_URL}/files/${d.id}`} target="_blank" rel="noreferrer" dir="auto">
                  {d.title}
                </a>
                <span className="facts">
                  {[partsCount(d.mime, d.page_count), plural(d.chunk_count, "passage")].filter(Boolean).join(", ")}
                </span>
                {d.status !== "ok" && (
                  <span className="problem" title={d.error ?? undefined}>{PROBLEM[d.status]}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
