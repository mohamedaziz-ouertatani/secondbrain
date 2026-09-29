"use client";

import { useCallback, useEffect, useState } from "react";
import { type AdminStatus, type EnrichmentStatus, getJSON, postJSON } from "@/lib/api";
import { ago } from "@/lib/seen";

const POLL_MS = 10_000;
const secs = (ms: number | null) => (ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`);
const mb = (bytes: number) => `${(bytes / 2 ** 20).toFixed(0)} MB`;

function servicesLine(s: AdminStatus["services"]): { ok: boolean; text: string } {
  if (!s) return { ok: false, text: "Couldn't check the services." };
  if (!s.db.ok) return { ok: false, text: "Database offline. Run docker compose up." };
  if (!s.ollama.reachable) return { ok: false, text: "Ollama isn't running. Start it from the tray or run ollama serve." };
  if (!s.ollama.llm_pulled || !s.ollama.embed_pulled)
    return { ok: false, text: "A model isn't pulled yet. See the README setup." };
  return { ok: true, text: "Database, Ollama and both models ready" };
}

function llmLine(l: AdminStatus["llm"]): string {
  if (l === null) return "Unknown: Ollama isn't answering";
  if (!l.loaded) return `${l.model} · not loaded (the next question loads it, ~10 s)`;
  const until = l.expires_at
    ? ` · unloads ${new Date(l.expires_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`
    : "";
  return `${l.model} · ${Math.round(l.gpu_share * 100)}% on the GPU${until}`;
}

function rerankerLine(r: AdminStatus["reranker"]): string {
  if (!r) return "Unknown";
  if (r.state === "ready") return "Ready on the GPU";
  if (r.state === "not loaded") return "Loads on the next question (a few seconds)";
  return `Off: ${r.reason}`;
}

/** System status, refreshed every 10 s while the tab is visible. */
function enrichLine(e: EnrichmentStatus): string {
  const c = e.counts;
  const parts = [`${c.ok}/${c.ok + c.error + c.pending} summarised`];
  if (c.error) parts.push(`${c.error} failed`);
  if (c.pending) parts.push(`${c.pending} to go`);
  if (e.state === "running" && e.current) parts.push(`summarising ${e.current}`);
  else if (e.state === "waiting") parts.push("waiting for a question or index job to finish");
  else if (e.state !== "idle" || c.pending) parts.push(e.state);
  return parts.join(" · ");
}

export function StatusCard() {
  const [s, setS] = useState<AdminStatus | null>(null);
  const [down, setDown] = useState(false);
  const [backingUp, setBackingUp] = useState(false);
  const [backupNote, setBackupNote] = useState<{ text: string; bad?: boolean } | null>(null);
  const [enrichBusy, setEnrichBusy] = useState(false);

  const load = useCallback(() => {
    if (document.visibilityState !== "visible") return;
    getJSON<AdminStatus>("/admin/status")
      .then((v) => {
        setS(v);
        setDown(false);
      })
      .catch(() => setDown(true));
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, POLL_MS);
    document.addEventListener("visibilitychange", load);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", load);
    };
  }, [load]);

  async function toggleEnrich(pause: boolean) {
    setEnrichBusy(true);
    try {
      const e = await postJSON<EnrichmentStatus>(`/admin/enrich/${pause ? "pause" : "resume"}`, {});
      setS((prev) => (prev ? { ...prev, enrichment: e } : prev));
    } finally {
      setEnrichBusy(false);
    }
  }

  async function backUpNow() {
    setBackingUp(true);
    setBackupNote(null);
    try {
      const r = await postJSON<{ rows: Record<string, number> }>("/admin/backup", {});
      setBackupNote({ text: `Backed up ${r.rows.query_log} questions and ${r.rows.excluded_paths} excluded files.` });
    } catch (e) {
      setBackupNote({ text: (e as Error).message, bad: true });
    } finally {
      setBackingUp(false);
      load();
    }
  }

  if (down && !s) return <p className="notice bad">Backend offline. Start it with uvicorn.</p>;
  if (!s) return <p className="muted">Checking the cabinet…</p>;

  const svc = servicesLine(s.services);
  const gpu = s.gpu;
  return (
    <section className="admin-card" aria-labelledby="status-h">
      <h2 id="status-h">Status</h2>
      {down && <p className="notice bad">Lost the backend. Showing the last reading.</p>}
      <dl className="kv">
        <dt>Services</dt>
        <dd className={svc.ok ? "ok" : "bad"}>{svc.text}</dd>

        <dt>LLM</dt>
        <dd>{llmLine(s.llm)}</dd>

        <dt>Reranker</dt>
        <dd className={s.reranker?.state === "off" && s.reranker.reason !== "turned off in Settings" ? "bad" : ""}>
          {rerankerLine(s.reranker)}
        </dd>

        <dt>GPU</dt>
        <dd>
          {gpu.available ? (
            <>
              <span>
                {gpu.name} · {gpu.used_mib} / {gpu.total_mib} MiB
              </span>
              <meter className="vram" min={0} max={gpu.total_mib} value={gpu.used_mib} high={gpu.total_mib * 0.9}>
                {Math.round((gpu.used_mib / gpu.total_mib) * 100)}%
              </meter>
            </>
          ) : (
            "Unavailable (nvidia-smi not found)"
          )}
        </dd>

        <dt>Answers</dt>
        <dd>
          {!s.answers
            ? "–"
            : s.answers.count === 0
              ? "No questions asked yet"
              : `Median ${secs(s.answers.median_ms)}, slowest ${secs(s.answers.max_ms)} over the last ${s.answers.count} · last asked ${ago(s.answers.last_at)}`}
        </dd>

        <dt>Index</dt>
        <dd>
          {s.index
            ? `${s.index.documents} documents · ${s.index.chunks} chunks · ${s.index.excluded} excluded · ${mb(s.index.db_bytes)} on disk · ${s.index.ocr.available ? `OCR on · ${s.index.ocr.pages} passages` : "OCR off: language data missing (python -m app.ingest.ocr --setup)"}`
            : "–"}
        </dd>

        <dt>Summaries</dt>
        <dd>
          {!s.enrichment ? (
            "–"
          ) : (
            <>
              <span>{enrichLine(s.enrichment)}</span>
              {s.enrichment.enabled && (
                <button
                  type="button"
                  className="quiet-btn"
                  onClick={() => toggleEnrich(!s.enrichment!.paused)}
                  disabled={enrichBusy}
                >
                  {s.enrichment.paused ? "Resume" : "Pause"}
                </button>
              )}
            </>
          )}
        </dd>

        <dt>Backup</dt>
        <dd>
          <span>
            {s.backup
              ? `Last backup ${ago(s.backup.at)} · ${Math.max(1, Math.round(s.backup.bytes / 1024))} KB · ${s.backup.kept} kept`
              : "No backup yet (the backend makes one within a few minutes of starting)"}
          </span>
          <button type="button" className="quiet-btn" onClick={backUpNow} disabled={backingUp}>
            {backingUp ? "Backing up…" : "Back up now"}
          </button>
          {backupNote && <span className={`action-note${backupNote.bad ? " bad" : ""}`}>{backupNote.text}</span>}
        </dd>
      </dl>
    </section>
  );
}
