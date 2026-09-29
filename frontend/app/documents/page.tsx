"use client";

import { ExternalLink, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";
import { API_URL, callNumber, type DocumentRow, fileUrl, kindOf, partsCount, readerUrl } from "@/lib/api";
import { folderOf, tintVar, unitOf } from "@/lib/modules";
import { ago, isNew, markSeen, newestFiled } from "@/lib/seen";
import { useDrawer, useLibrary } from "@/lib/useLibrary";

const PROBLEM: Record<Exclude<DocumentRow["status"], "ok">, string> = {
  empty_text: "No text layer: a scanned file, not searchable yet",
  error: "Couldn't be read",
};

const loose = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");

/** Synced notes are titled "Page — Section"; under that section's guide card the suffix is noise. */
function shortTitle(d: DocumentRow): string {
  const section = d.path.split("/").slice(-2, -1)[0] ?? "";
  const m = /^(.*) — (.+)$/.exec(d.title);
  return m && section && loose(m[2]) === loose(section) ? m[1] : d.title;
}

function DrawerView() {
  const drawer = useDrawer();
  const { docs, error, reload } = useLibrary();
  const [query, setQuery] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanNote, setScanNote] = useState<string | null>(null);

  async function rescan() {
    setScanning(true);
    setScanNote(null);
    try {
      const r = await fetch(`${API_URL}/ingest/rescan`, { method: "POST" });
      const s = await r.json();
      setScanNote(
        r.ok
          ? `Rescanned: ${s.ok ?? 0} filed, ${s.skipped ?? 0} unchanged, ${s.removed ?? 0} removed.`
          : "A rescan is already running.",
      );
    } catch {
      setScanNote(`Can't reach the backend at ${API_URL}.`);
    } finally {
      setScanning(false);
      reload();
    }
  }

  const q = query.trim().toLowerCase();
  const rows = (docs ?? []).filter(
    (d) =>
      (drawer === null || d.course === drawer) &&
      (!q || `${d.title} ${d.path} ${d.summary ?? ""} ${(d.concepts ?? []).join(" ")}`.toLowerCase().includes(q)),
  );
  const groups = new Map<string, DocumentRow[]>();
  for (const d of rows) {
    const folder = folderOf(d.path);
    const key = drawer === null ? [d.course ?? "Loose notes", folder].filter(Boolean).join(" › ") : folder || "Top of the drawer";
    groups.set(key, [...(groups.get(key) ?? []), d]);
  }
  const total = (docs ?? []).filter((d) => drawer === null || d.course === drawer);

  return (
    <div className="drawer-view" style={{ "--tint": tintVar(drawer) } as React.CSSProperties}>
      <header className="drawer-head">
        <div>
          <h1>{drawer ?? "All drawers"}</h1>
          <p>
            {drawer ? `${unitOf(drawer).name} · ` : ""}
            {total.length} fiche{total.length === 1 ? "" : "s"}
            {total.length > 0 && ` · last filed ${ago(newestFiled(total))}`}
          </p>
        </div>
        <div className="drawer-tools">
          <label className="search">
            <Search size={15} aria-hidden />
            <span className="sr-only">Filter this drawer</span>
            <input
              type="search"
              dir="auto"
              value={query}
              placeholder="Filter by title, folder or topic"
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <button type="button" className="quiet-btn" onClick={rescan} disabled={scanning}>
            <RefreshCw size={15} aria-hidden className={scanning ? "spin" : undefined} />
            {scanning ? "Rescanning…" : "Rescan inbox"}
          </button>
        </div>
      </header>

      {scanNote && <p className="notice">{scanNote}</p>}
      {error && <p className="notice bad">{error} Start it with uvicorn, then reload.</p>}

      {docs && total.length === 0 && (
        <section className="digest">
          <h2>This drawer is empty</h2>
          <p>
            Nothing has been posted on Blackboard for it yet, or it hasn&apos;t been synced. Run{" "}
            <code>uv run python -m app.sync.blackboard --headless</code> in <code>backend/</code>.
          </p>
        </section>
      )}
      {docs && total.length > 0 && rows.length === 0 && <p className="notice">No fiche matches “{query}”.</p>}

      {rows.length > 0 && (
        <div className="drawer-table" role="table" aria-label={`Fiches in ${drawer ?? "all drawers"}`}>
          <div className="row head" role="row">
            <span role="columnheader">Call number</span>
            <span role="columnheader">Title</span>
            <span role="columnheader">Kind</span>
            <span role="columnheader">Passages</span>
            <span role="columnheader">
              <span className="sr-only">Original</span>
            </span>
          </div>
      {[...groups]
        .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }))
        .map(([folder, list], i) => (
        <section
          key={folder}
          className="guide"
          role="rowgroup"
          aria-label={folder}
          style={{ "--stagger": i % 3 } as React.CSSProperties}
        >
          <h2 className="guide-tab" dir="auto">
            {folder}
          </h2>
          <div className="catalogue">
            {list.map((d) => {
              const fresh = isNew(d);
              return (
                <div key={d.id} role="row" className={`row${d.status !== "ok" ? " problem" : ""}`}>
                  <span role="cell" className="callno">
                    {callNumber({ ...d, page: 0, mime: "" })}
                  </span>
                  <span role="cell" className="title-cell">
                    <Link href={readerUrl(d.id)} dir="auto" onClick={() => markSeen(d.id)}>
                      {shortTitle(d)}
                    </Link>
                    {fresh && <span className="fresh">new</span>}
                    {d.status !== "ok" && (
                      <span className="problem-note" title={d.error ?? undefined}>
                        {PROBLEM[d.status]}
                      </span>
                    )}
                    {d.status === "ok" && d.summary && (
                      <span className="summary-line" dir="auto" title={d.summary}>
                        {d.summary}
                      </span>
                    )}
                    {d.enrich_status === "pending" && !d.summary && <span className="enrich-note">summarising…</span>}
                    {d.enrich_status === "error" && (
                      <span className="enrich-note" title={d.enrich_error ?? undefined}>
                        no summary
                      </span>
                    )}
                  </span>
                  <span role="cell" className="num">
                    {[kindOf(d.mime), partsCount(d.mime, d.page_count)].filter(Boolean).join(" · ")}
                  </span>
                  <span role="cell" className="num">
                    {d.chunk_count}
                  </span>
                  <span role="cell">
                    <a
                      className="icon-only"
                      href={fileUrl({ doc_id: d.id, mime: d.mime })}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`Open the original of ${d.title}`}
                      onClick={() => markSeen(d.id)}
                    >
                      <ExternalLink size={15} aria-hidden />
                    </a>
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      ))}
        </div>
      )}
    </div>
  );
}

export default function DocumentsPage() {
  return (
    <Suspense>
      <DrawerView />
    </Suspense>
  );
}
