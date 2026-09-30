"use client";

import { useCallback, useEffect, useState } from "react";
import { Explain } from "@/components/admin/Explain";
import { metricHelp } from "@/lib/adminHelp";
import { type EvalMetrics, type EvalMode, type EvalRun, type EvalStatus, getJSON, postJSON } from "@/lib/api";
import { moduleCode, tintVar } from "@/lib/modules";
import { recallReading } from "@/lib/readings";

const POLL_MS = 1500;
const ROWS: { key: keyof EvalMetrics; label: string; lowerIsBetter?: boolean; pct: boolean }[] = [
  { key: "recall@1", label: "Right page first (recall@1)", pct: true },
  { key: "recall@5", label: "Right page in top 5 (recall@5)", pct: true },
  { key: "recall@20", label: "Right page in top 20 (recall@20)", pct: true },
  { key: "mrr", label: "Mean reciprocal rank (MRR)", pct: false },
  { key: "refusal_rate", label: "Refused", lowerIsBetter: true, pct: true },
];

const show = (v: number | undefined, pct: boolean) =>
  v === undefined ? "–" : pct ? `${Math.round(v * 100)}%` : v.toFixed(2);

const MODES: { key: EvalMode; label: string }[] = [
  { key: "dense", label: "Dense" },
  { key: "hybrid", label: "Hybrid" },
  { key: "dense+rerank", label: "Reranked" },
];

/** Which columns hold the best value; none when fewer than two are known or all tie. */
function best(values: (number | undefined)[], lowerIsBetter?: boolean): boolean[] {
  const known = values.filter((v): v is number => v !== undefined);
  if (known.length < 2 || known.every((v) => v === known[0])) return values.map(() => false);
  const top = lowerIsBetter ? Math.min(...known) : Math.max(...known);
  return values.map((v) => v === top);
}

function jobLine(s: EvalStatus): string | null {
  const j = s.job;
  if (!j) return null;
  const verb = j.kind === "generate" ? "Generating questions" : "Evaluating";
  if (j.state === "running") return `${verb} ${j.done}/${j.total || "…"}…`;
  if (j.state === "cancelled") return "Cancelled.";
  if (j.state === "failed") return `Failed: ${j.error}`;
  if (j.kind === "generate" && j.result) {
    const rej = Object.entries(j.result.rejected ?? {});
    const n = rej.reduce((a, [, k]) => a + k, 0);
    return `Added ${j.result.accepted} questions${n ? ` (${n} rejected: ${rej.map(([r, k]) => `${k} ${r}`).join(", ")})` : ""}.`;
  }
  return j.result?.run_id ? `Run ${j.result.run_id} saved.` : null;
}

function delta(run: EvalRun, prev: EvalRun | undefined): string {
  if (!prev) return "";
  const a = run.metrics.overall.dense["recall@5"];
  const b = prev.metrics.overall.dense["recall@5"];
  if (a === undefined || b === undefined) return "";
  const d = Math.round((a - b) * 100);
  return d === 0 ? " (±0)" : ` (${d > 0 ? "+" : "−"}${Math.abs(d)} pts)`;
}

/** How well retrieval finds the right page, measured on generated (and, later, your labelled) questions. */
export function EvalCard() {
  const [s, setS] = useState<EvalStatus | null>(null);
  const [n, setN] = useState(150);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getJSON<EvalStatus>("/admin/eval")
      .then(setS)
      .catch(() => setError("Couldn't load the evaluation."));
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

  if (!s) return <p className="muted">{error ?? "Reading the evaluation…"}</p>;
  const latest = s.latest;
  const line = jobLine(s);

  return (
    <section className="admin-card" id="eval" aria-labelledby="eval-h">
      <header className="admin-card-head">
        <h2 id="eval-h">Evaluation</h2>
        {running && (
          <button type="button" className="quiet-btn" onClick={() => post("/admin/eval/cancel", {})}>
            Cancel
          </button>
        )}
      </header>
      <p className="muted">
        {s.questions.generated} generated questions · {s.questions.labelled} of your questions labelled
      </p>

      <div className="sync-actions">
        <label className="sr-only" htmlFor="eval-n">
          How many questions
        </label>
        <input
          id="eval-n"
          className="eval-n"
          type="number"
          min={1}
          max={500}
          value={n}
          disabled={running}
          onChange={(e) => setN(Number.parseInt(e.target.value, 10) || 1)}
        />
        <button
          type="button"
          className="quiet-btn"
          disabled={running}
          onClick={() => post("/admin/eval/generate", { n })}
        >
          Generate questions
        </button>
        <button
          type="button"
          className="quiet-btn"
          disabled={running || s.questions.generated + s.questions.labelled === 0}
          onClick={() => post("/admin/eval/run", { kind: "retrieval" })}
        >
          Run evaluation
        </button>
        <button
          type="button"
          className="quiet-btn"
          disabled={running || s.questions.generated + s.questions.labelled === 0}
          onClick={() => post("/admin/eval/run", { kind: "full" })}
          title="Also answers every question with your model, to check citations (about 20 minutes)"
        >
          Full run (~20 min)
        </button>
      </div>
      {line && (
        <p className={s.job?.state === "failed" ? "action-note bad" : "action-note"} aria-live="polite">
          {line}
        </p>
      )}
      {error && <p className="action-note bad">{error}</p>}

      {!latest ? (
        <p className="muted">
          {s.questions.generated === 0
            ? "No questions yet: generate a set to start (about 8 minutes for 150; your model writes them)."
            : "No run yet: run an evaluation (about a minute)."}
        </p>
      ) : (
        <>
          <table className="admin-table eval-table">
            <caption className="muted">
              Run {latest.id} · {new Date(latest.ts).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}{" "}
              · {latest.params.questions} questions · top_k {latest.params.top_k} · min_score {latest.params.min_score}
            </caption>
            <thead>
              <tr>
                <th scope="col">Measure</th>
                {MODES.map((m) => (
                  <th key={m.key} scope="col">
                    {m.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) => {
                const vals = MODES.map((m) => latest.metrics.overall[m.key]?.[r.key] as number | undefined);
                const wins = best(vals, r.lowerIsBetter);
                return (
                  <tr key={r.key}>
                    <th scope="row">
                      {r.label}
                      <Explain more={metricHelp[r.key]} />
                    </th>
                    {vals.map((v, i) => (
                      <td key={MODES[i].key} className={wins[i] ? "eval-better" : ""}>
                        {show(v, r.pct)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {(() => {
            const m = latest.metrics.overall["dense+rerank"]?.["recall@5"] !== undefined ? MODES[2] : MODES[0];
            const r = recallReading(5, latest.metrics.overall[m.key]?.["recall@5"]);
            return r && <Explain line={`${m.label}: ${r}.`} />;
          })()}

          {latest.metrics.answers && (
            <>
              <h3>
                Answers ({String(latest.params.retrieval_mode)}, top_k {String(latest.params.top_k)})
              </h3>
              <dl className="kv">
                <dt>Refused</dt>
                <dd>{show(latest.metrics.answers.refusal_rate ?? undefined, true)}</dd>
                <dt>Citations valid</dt>
                <dd>
                  {show(latest.metrics.answers.citation_valid_rate ?? undefined, true)}
                  <Explain more={metricHelp.citation_valid_rate} />
                </dd>
                <dt>Cited the right page</dt>
                <dd>
                  {show(latest.metrics.answers.cited_right_rate ?? undefined, true)}
                  <Explain more={metricHelp.cited_right_rate} />
                </dd>
                <dt>Median answer time</dt>
                <dd>
                  {latest.metrics.answers.median_ms === null
                    ? "–"
                    : `${(latest.metrics.answers.median_ms / 1000).toFixed(1)} s`}
                </dd>
              </dl>
            </>
          )}

          <h3>Right page in top 5, by module</h3>
          <table className="admin-table eval-table">
            <thead>
              <tr>
                <th scope="col">Module</th>
                <th scope="col">Questions</th>
                {MODES.map((x) => (
                  <th key={x.key} scope="col">
                    {x.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(latest.metrics.by_course).map(([course, m]) => {
                const name = course === "None" ? null : course;
                const vals = MODES.map((x) => m[x.key]?.["recall@5"]);
                const wins = best(vals);
                return (
                  <tr key={course}>
                    <th scope="row">
                      <span className="label-card" style={{ "--tint": tintVar(name) } as React.CSSProperties}>
                        {name ? moduleCode(name) : "—"}
                      </span>{" "}
                      {name ?? "No module"}
                    </th>
                    <td>{m.dense.n}</td>
                    {vals.map((v, i) => (
                      <td key={MODES[i].key} className={wins[i] ? "eval-better" : ""}>
                        {show(v, true)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>

          {s.runs.length > 1 && (
            <details className="sync-runs">
              <summary>Run history</summary>
              <ul className="admin-list">
                {s.runs.map((r, i) => {
                  const prev = s.runs.slice(i + 1).find((p) => p.kind === r.kind);
                  return (
                    <li key={r.id}>
                      <span className="admin-item">
                        <strong>
                          Run {r.id} · {r.kind}
                        </strong>
                        <span className="muted">
                          {new Date(r.ts).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })} · dense
                          top 5 {show(r.metrics.overall.dense["recall@5"], true)}
                          <span className="eval-delta">{delta(r, prev)}</span> · MRR{" "}
                          {show(r.metrics.overall.dense.mrr, false)}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}
