"use client";

import { useCallback, useEffect, useState } from "react";
import { type AdminLibrary, API_URL, getJSON, postJSON } from "@/lib/api";
import { moduleCode, tintVar } from "@/lib/modules";

type Note = { key: string; text: string; bad?: boolean } | null;

const counts = (r: Record<string, number>) =>
  Object.entries(r)
    .map(([k, n]) => `${n} ${k.replace("_", " ")}`)
    .join(", ") || "nothing to do";

/** Per-module counts, problem files, excluded files; rescan, re-index, exclude, include. */
export function LibraryAdmin() {
  const [lib, setLib] = useState<AdminLibrary | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<Note>(null);

  const reload = useCallback(() => {
    getJSON<AdminLibrary>("/admin/library")
      .then((l) => {
        setLib(l);
        setError(false);
      })
      .catch(() => setError(true));
  }, []);
  useEffect(reload, [reload]);

  async function act(key: string, run: () => Promise<string>) {
    setBusy(key);
    setNote(null);
    try {
      setNote({ key, text: await run() });
    } catch (e) {
      setNote({ key, text: (e as Error).message, bad: true });
    } finally {
      setBusy(null);
      reload();
    }
  }

  const rescan = () =>
    act("rescan", async () => {
      const s = await postJSON<Record<string, number>>("/ingest/rescan", {});
      return `Rescanned: ${counts(s)}.`;
    });
  const reenrich = (key: string, body: { course: string } | { document_id: number }) =>
    act(key, async () => {
      const r = await postJSON<{ queued: number }>("/admin/enrich/rerun", body);
      return `Queued ${r.queued} file${r.queued === 1 ? "" : "s"} for new summaries.`;
    });
  const reindex = (key: string, body: { path?: string; course?: string }) =>
    act(key, async () => `Re-indexed: ${counts(await postJSON<Record<string, number>>("/admin/reindex", body))}.`);
  const exclude = (path: string) =>
    act(`x:${path}`, async () => {
      const r = await postJSON<{ removed: boolean }>("/admin/exclude", { path });
      return r.removed ? "Excluded and removed from the index." : "Excluded.";
    });
  const include = (path: string) =>
    act(`i:${path}`, async () => {
      const r = await postJSON<{ status: string }>("/admin/include", { path });
      return r.status === "missing"
        ? "Included, but the file is no longer on disk."
        : `Included and filed (${r.status.replace("_", " ")}).`;
    });

  const inline = (key: string) =>
    note?.key === key && <span className={`action-note${note.bad ? " bad" : ""}`}>{note.text}</span>;
  const btn = (key: string, label: string, onClick: () => void) => (
    <button type="button" className="quiet-btn" onClick={onClick} disabled={busy !== null}>
      {busy === key ? "Working…" : label}
    </button>
  );

  if (error && !lib) return <p className="notice bad">Couldn&apos;t load the library from {API_URL}.</p>;
  if (!lib) return <p className="muted">Counting the drawers…</p>;

  return (
    <section className="admin-card" id="library" aria-labelledby="library-h">
      <header className="admin-card-head">
        <h2 id="library-h">Library</h2>
        <span className="admin-actions">
          {inline("rescan")}
          {btn("rescan", "Rescan inbox", rescan)}
        </span>
      </header>

      <table className="admin-table library-table">
        <thead>
          <tr>
            <th scope="col">Module</th>
            <th scope="col">Documents</th>
            <th scope="col">Chunks</th>
            <th scope="col">Problems</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {lib.modules.map((m) => {
            const key = `m:${m.course}`;
            return (
              <tr key={m.course ?? ""}>
                <th scope="row">
                  <span className="label-card" style={{ "--tint": tintVar(m.course) } as React.CSSProperties}>
                    {moduleCode(m.course)}
                  </span>{" "}
                  {m.course ?? "Loose files"}
                </th>
                <td>{m.documents}</td>
                <td>{m.chunks}</td>
                <td>{m.problems || "–"}</td>
                <td>
                  <span className="row-actions">
                    {inline(key)}
                    {m.course && btn(key, "Re-index", () => reindex(key, { course: m.course! }))}
                    {inline(`e:${m.course}`)}
                    {m.course && btn(`e:${m.course}`, "Re-enrich", () => reenrich(`e:${m.course}`, { course: m.course! }))}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3>Problem files</h3>
      {lib.problems.length === 0 ? (
        <p className="muted">Every file was read and indexed.</p>
      ) : (
        <ul className="admin-list">
          {lib.problems.map((p) => (
            <li key={p.id}>
              <span className="admin-item">
                <strong dir="auto">{p.title}</strong>
                <span className="callno">{p.path}</span>
                <span className="muted">
                  {p.status === "empty_text"
                    ? "No text layer: a scanned file, not searchable yet"
                    : (p.error ?? "Couldn't be read")}
                </span>
              </span>
              <span className="row-actions">
                {inline(`r:${p.path}`)}
                {inline(`x:${p.path}`)}
                {btn(`r:${p.path}`, "Re-index", () => reindex(`r:${p.path}`, { path: p.path }))}
                {btn(`x:${p.path}`, "Exclude", () => exclude(p.path))}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3>Couldn&apos;t summarise</h3>
      {lib.summary_errors.length === 0 ? (
        <p className="muted">Every summarised file has a summary.</p>
      ) : (
        <ul className="admin-list">
          {lib.summary_errors.map((p) => (
            <li key={p.id}>
              <span className="admin-item">
                <strong dir="auto">{p.title}</strong>
                <span className="callno">{p.path}</span>
                <span className="muted">{p.error ?? "The model's reply wasn't usable"}</span>
              </span>
              <span className="row-actions">
                {inline(`s:${p.id}`)}
                {btn(`s:${p.id}`, "Re-enrich", () => reenrich(`s:${p.id}`, { document_id: p.id }))}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h3>Excluded</h3>
      {lib.excluded.length === 0 ? (
        <p className="muted">Nothing excluded. Exclude a file to keep it on disk but out of your answers.</p>
      ) : (
        <ul className="admin-list">
          {lib.excluded.map((e) => (
            <li key={e.path}>
              <span className="admin-item">
                <span className="callno">{e.path}</span>
                <span className="muted">
                  Excluded {new Date(e.excluded_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                  {e.on_disk ? "" : " · no longer on disk"}
                </span>
              </span>
              <span className="row-actions">
                {inline(`i:${e.path}`)}
                {btn(`i:${e.path}`, "Include", () => include(e.path))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
