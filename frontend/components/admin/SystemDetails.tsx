"use client";

import { useAdminData } from "@/components/admin/AdminData";
import { Explain } from "@/components/admin/Explain";
import type { AdminStatus, EnrichmentStatus } from "@/lib/api";
import { detailHelp } from "@/lib/adminHelp";
import { gpuShareReading, servicesReading, vramReading } from "@/lib/readings";
import { ago } from "@/lib/seen";

const secs = (ms: number | null) => (ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`);
const mb = (bytes: number) => `${(bytes / 2 ** 20).toFixed(0)} MB`;

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

/** The full system reading: services, model, reranker, GPU, answer times, index and summaries. */
export function SystemDetails() {
  const { status } = useAdminData();
  const s = status.value;
  if (!s) return status.failed ? null : <p className="muted">Checking the cabinet…</p>;

  const svc = servicesReading(s.services);
  const gpu = s.gpu;
  return (
    <section className="admin-card" id="details" aria-labelledby="details-h">
      <h2 id="details-h">System details</h2>
      {status.failed && <p className="notice bad">Lost the backend. Showing the last reading.</p>}
      <dl className="kv">
        <dt>Services</dt>
        <dd className={svc.ok ? "ok" : "bad"}>{svc.text}</dd>

        <dt>LLM</dt>
        <dd>
          <span>{llmLine(s.llm)}</span>
          <Explain line={s.llm?.loaded ? gpuShareReading(s.llm.gpu_share) : null} more={detailHelp.llm} />
        </dd>

        <dt>Reranker</dt>
        <dd className={s.reranker?.state === "off" && s.reranker.reason !== "turned off in Settings" ? "bad" : ""}>
          <span>{rerankerLine(s.reranker)}</span>
          <Explain more={detailHelp.reranker} />
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
              <Explain line={vramReading(gpu.used_mib, gpu.total_mib)} more={detailHelp.gpu} />
            </>
          ) : (
            "Unavailable (nvidia-smi not found)"
          )}
        </dd>

        <dt>Answers</dt>
        <dd>
          <span>
            {!s.answers
              ? "–"
              : s.answers.count === 0
                ? "No questions asked yet"
                : `Median ${secs(s.answers.median_ms)}, slowest ${secs(s.answers.max_ms)} over the last ${s.answers.count} · last asked ${ago(s.answers.last_at)}`}
          </span>
          <Explain more={detailHelp.answers} />
        </dd>

        <dt>Index</dt>
        <dd>
          <span>
            {s.index
              ? `${s.index.documents} documents · ${s.index.chunks} chunks · ${s.index.excluded} excluded · ${mb(s.index.db_bytes)} on disk · ${s.index.ocr.available ? `OCR on · ${s.index.ocr.pages} passages` : "OCR off: language data missing (python -m app.ingest.ocr --setup)"}`
              : "–"}
          </span>
          <Explain more={detailHelp.index} />
        </dd>

        <dt>Summaries</dt>
        <dd>
          <span>{s.enrichment ? enrichLine(s.enrichment) : "–"}</span>
          <Explain more={detailHelp.summaries} />
        </dd>
      </dl>
    </section>
  );
}
