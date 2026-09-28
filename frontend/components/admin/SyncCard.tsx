"use client";

import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON, type SyncAction, type SyncJob, type SyncStatus } from "@/lib/api";
import { ago } from "@/lib/seen";

const POLL_MS = 1500;
const ACTION: Record<SyncAction, string> = {
  downloaded: "Downloaded",
  saved_page: "Saved page",
  already_had: "Already had",
  would_download: "Would download",
  would_save_page: "Would save page",
  failed: "Failed",
};
const MODE: Record<SyncJob["mode"], string> = {
  sync: "Sync",
  preview: "Preview",
  probe: "Course mapping",
  login: "Log in",
};
const mb = (b: number) => `${(b / 1_048_576).toFixed(1)} MB`;

function until(iso: string): string {
  const days = Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000);
  return days <= 0 ? "at the next hourly check" : `in ${days} day${days === 1 ? "" : "s"}`;
}

function outcome(j: SyncJob): string {
  const c = j.counts;
  if (j.state === "running") return `${MODE[j.mode]} running…`;
  if (j.state === "cancelled") return "Cancelled.";
  if (j.state === "login_required") return "Your Blackboard session expired: log in, then sync again.";
  if (j.state === "failed") return `Failed: ${j.error ?? `the sync exited with code ${j.exit_code}`}`;
  if (j.mode === "probe") return "Course mapping below.";
  if (j.mode === "login") return "Logged in. The session is saved for the next syncs.";
  if (j.mode === "preview") {
    const n = c.would_download + c.would_save_page;
    return n ? `Preview: ${n} file${n === 1 ? "" : "s"} would be downloaded.` : "Preview: everything is up to date.";
  }
  const n = c.downloaded + c.saved_page;
  return `Done: ${n} file${n === 1 ? "" : "s"}, ${mb(j.bytes)}${c.failed ? `, ${c.failed} failed (retried next time)` : ""}.`;
}

/** Blackboard sync: run it, watch it, and see when it last ran and runs next. */
export function SyncCard() {
  const [s, setS] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [course, setCourse] = useState("");

  const load = useCallback(() => {
    getJSON<SyncStatus>("/admin/sync")
      .then((v) => {
        setS(v);
        setError(null);
      })
      .catch(() => setError("Couldn't reach the backend."));
  }, []);
  useEffect(load, [load]);

  const running = s?.job?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(t);
  }, [running, load]);

  async function post(path: string, body: unknown) {
    setError(null);
    try {
      await postJSON(path, body);
    } catch (e) {
      setError((e as Error).message);
    }
    load();
  }

  if (!s) return <p className="muted">{error ?? "Checking the sync…"}</p>;
  const job = s.job;
  const files = (job?.events ?? []).filter((e) => e.type === "file");
  const byFolder = new Map<string, typeof files>();
  for (const e of [...files].reverse()) {
    const f = String(e.folder);
    byFolder.set(f, [...(byFolder.get(f) ?? []), e]);
  }
  const lastFull = s.runs.find((r) => r.mode === "sync" && !r.course && r.state === "ok");

  return (
    <section className="admin-card" id="sync" aria-labelledby="sync-h">
      <header className="admin-card-head">
        <h2 id="sync-h">Blackboard sync</h2>
        {running && (
          <button type="button" className="quiet-btn" onClick={() => post("/admin/sync/cancel", {})}>
            Cancel
          </button>
        )}
      </header>

      <p className="muted">
        {s.last_full_sync ? `Last full sync ${ago(s.last_full_sync)}` : "Never synced from here"}
        {lastFull ? ` · ${lastFull.counts.downloaded + lastFull.counts.saved_page} files` : ""} ·{" "}
        {s.auto_days === 0
          ? "Automatic sync off"
          : s.next_auto
            ? `Next automatic sync ${until(s.next_auto)}`
            : "Automatic sync paused"}
      </p>

      {s.login_needed && (
        <p className="notice sync-login">
          Your Blackboard session expired. Log in to sync again: an Edge window opens for you to sign in, and the
          session is saved.{" "}
          <button type="button" className="quiet-btn" disabled={running} onClick={() => post("/admin/sync/login", {})}>
            Log in
          </button>
        </p>
      )}

      <div className="sync-actions">
        <button
          type="button"
          className="quiet-btn"
          disabled={running}
          onClick={() => post("/admin/sync", { mode: "sync" })}
        >
          Sync now
        </button>
        <button
          type="button"
          className="quiet-btn"
          disabled={running}
          onClick={() => post("/admin/sync", { mode: "preview" })}
        >
          Preview
        </button>
        <button
          type="button"
          className="quiet-btn"
          disabled={running}
          onClick={() => post("/admin/sync", { mode: "probe" })}
        >
          Course mapping
        </button>
        <span className="sync-one">
          <label className="sr-only" htmlFor="sync-course">
            Module
          </label>
          <select id="sync-course" value={course} onChange={(e) => setCourse(e.target.value)} disabled={running}>
            <option value="">Choose a module…</option>
            {s.modules.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="quiet-btn"
            disabled={running || !course}
            onClick={() => post("/admin/sync", { mode: "sync", course })}
          >
            Sync this module
          </button>
        </span>
      </div>
      {error && <p className="action-note bad">{error}</p>}

      {job && (
        <div className="sync-job" aria-live="polite">
          <p className={job.state === "failed" || job.state === "login_required" ? "bad" : ""}>
            <strong>
              {MODE[job.mode]}
              {job.course ? ` · ${job.course}` : ""}
            </strong>{" "}
            {outcome(job)}
          </p>
          {files.length > 0 && (
            <div className="sync-log">
              {[...byFolder].map(([folder, evs]) => (
                <section key={folder}>
                  <h3>{folder}</h3>
                  <ul>
                    {evs.map((e, i) => (
                      <li key={`${String(e.path)}-${i}`} className={e.action === "failed" ? "bad" : ""}>
                        <span className="sync-action">{ACTION[e.action as SyncAction]}</span>
                        <span className="callno">{String(e.path).split("/").slice(1).join("/")}</span>
                        {e.action === "failed" && <span> {String(e.error)}</span>}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}
          {job.mode === "probe" && job.courses && (
            <>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th scope="col">Blackboard course</th>
                    <th scope="col">Inbox folder</th>
                  </tr>
                </thead>
                <tbody>
                  {job.courses.map((c) => (
                    <tr key={c.name} className={c.folder ? "" : "muted"}>
                      <th scope="row">{c.name}</th>
                      <td>{c.folder ?? "skipped: no inbox folder"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted">Fix wrong matches with blackboard_course_map in config.yaml.</p>
            </>
          )}
        </div>
      )}

      {s.runs.length > 0 && (
        <details className="sync-runs">
          <summary>Recent runs</summary>
          <ul className="admin-list">
            {s.runs.map((r) => (
              <li key={r.id}>
                <span className="admin-item">
                  <strong>
                    {MODE[r.mode]}
                    {r.course ? ` · ${r.course}` : ""}
                  </strong>
                  <span className="muted">
                    {ago(r.started_at)} · {outcome(r)}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
