"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { TrendChart } from "@/components/admin/TrendChart";
import { type CompareResult, getJSON, type InsightsSummary, postJSON, type ProblemRow } from "@/lib/api";
import { openHref } from "@/lib/history";
import { moduleCode, tintVar } from "@/lib/modules";

const PERIODS = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 0, label: "All" },
];
const KINDS = [
  { kind: "refused", label: "Refused" },
  { kind: "invalid", label: "Invalid citations" },
  { kind: "slow", label: "Slowest" },
] as const;
type Kind = (typeof KINDS)[number]["kind"];

const pct = (n: number, of: number) => (of ? `${Math.round((n / of) * 100)}%` : "–");
const secs = (ms: number | null) => (ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`);

/** What the query log says: volume, refusals, citations, speed, trend, problems, and dense vs hybrid. */
export function InsightsCard() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [days, setDays] = useState(7);
  const [kind, setKind] = useState<Kind>("refused");
  const [data, setData] = useState<{ key: string; s: InsightsSummary } | null>(null);
  const [rows, setRows] = useState<{ key: string; r: ProblemRow[] } | null>(null);
  const [error, setError] = useState(false);
  const [cmp, setCmp] = useState<CompareResult | null>(null);
  const [cmpBusy, setCmpBusy] = useState(false);
  const [cmpError, setCmpError] = useState<string | null>(null);

  useEffect(() => {
    getJSON<InsightsSummary>(`/admin/insights?days=${days}&tz=${encodeURIComponent(tz)}`)
      .then((s) => setData({ key: `${days}`, s }))
      .catch(() => setError(true));
  }, [days, tz]);
  useEffect(() => {
    getJSON<ProblemRow[]>(`/admin/insights/problems?kind=${kind}&days=${days}&limit=20`)
      .then((r) => setRows({ key: `${days}:${kind}`, r }))
      .catch(() => setError(true));
  }, [days, kind]);

  async function runCompare() {
    setCmpBusy(true);
    setCmpError(null);
    try {
      setCmp(await postJSON<CompareResult>("/admin/compare", { limit: 20 }));
    } catch (e) {
      setCmpError((e as Error).message);
    } finally {
      setCmpBusy(false);
    }
  }

  const s = data?.key === `${days}` ? data.s : null;
  const problems = rows?.key === `${days}:${kind}` ? rows.r : null;

  return (
    <section className="admin-card" id="insights" aria-labelledby="insights-h">
      <header className="admin-card-head">
        <h2 id="insights-h">Insights</h2>
        <span className="tabs" role="tablist" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p.days} type="button" role="tab" aria-selected={days === p.days} onClick={() => setDays(p.days)}>
              {p.label}
            </button>
          ))}
        </span>
      </header>

      {error && <p className="notice bad">Couldn&apos;t load the query log.</p>}
      {!s ? (
        <p className="muted">Reading the query log…</p>
      ) : (
        <>
          <dl className="kv">
            <dt>Questions</dt>
            <dd>{s.questions}</dd>
            <dt>Refused</dt>
            <dd>
              {s.refused} ({pct(s.refused, s.questions)}): not in your fiches
            </dd>
            <dt>Invalid citations</dt>
            <dd>
              {s.invalid} ({pct(s.invalid, s.questions)}){s.failed ? ` · ${s.failed} failed before answering` : ""}
            </dd>
            <dt>Answer time</dt>
            <dd>
              Median {secs(s.median_ms)}, slowest {secs(s.max_ms)}
            </dd>
          </dl>

          <h3>Trend</h3>
          <TrendChart days={days} data={s.per_day} />

          <h3>By module</h3>
          <table className="admin-table">
            <thead>
              <tr>
                <th scope="col">Module</th>
                <th scope="col">Questions</th>
                <th scope="col">Refused</th>
              </tr>
            </thead>
            <tbody>
              {s.per_module.map((m) => (
                <tr key={m.course ?? ""}>
                  <th scope="row">
                    <span className="label-card" style={{ "--tint": tintVar(m.course) } as React.CSSProperties}>
                      {m.course ? moduleCode(m.course) : "ALL"}
                    </span>{" "}
                    {m.course ?? "All drawers"}
                  </th>
                  <td>{m.questions}</td>
                  <td>{m.refused || "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h3>Problems</h3>
      <span className="tabs" role="tablist" aria-label="Problem kind">
        {KINDS.map((k) => (
          <button key={k.kind} type="button" role="tab" aria-selected={kind === k.kind} onClick={() => setKind(k.kind)}>
            {k.label}
          </button>
        ))}
      </span>
      {!problems ? (
        <p className="muted">Loading…</p>
      ) : problems.length === 0 ? (
        <p className="muted">None in this period.</p>
      ) : (
        <ul className="admin-list">
          {problems.map((p) => (
            <li key={p.id}>
              <Link className="admin-item problem-link" href={openHref(p.id, null)}>
                <strong dir="auto">{p.question}</strong>
                <span className="muted">
                  {p.course ?? "All drawers"} ·{" "}
                  {new Date(p.ts).toLocaleString("en-GB", {
                    day: "numeric",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                  {kind === "slow" ? ` · ${secs(p.latency_ms)}` : ""}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <h3>Dense vs hybrid</h3>
      <p className="muted">
        Replays your 20 most recent distinct questions through both retrieval modes. It doesn&apos;t ask the model.
      </p>
      <p>
        <button type="button" className="quiet-btn" onClick={runCompare} disabled={cmpBusy}>
          {cmpBusy ? "Comparing…" : "Compare"}
        </button>
        {cmpError && <span className="action-note bad"> {cmpError}</span>}
      </p>
      {cmp && (
        <>
          <p>
            {cmp.summary.changed} of {cmp.summary.questions} questions would get different passages;{" "}
            {cmp.summary.flipped} would change between answering and refusing.
          </p>
          <ul className="admin-list compare">
            {cmp.rows
              .filter((r) => r.changed || r.verdict_dense !== r.verdict_hybrid)
              .map((r) => {
                const dense = new Set(r.dense.map((h) => h.chunk_id));
                const hybrid = new Set(r.hybrid.map((h) => h.chunk_id));
                return (
                  <li key={`${r.question}|${r.course}`}>
                    <span className="admin-item">
                      <strong dir="auto">{r.question}</strong>
                      <span className="muted">
                        {r.course ?? "All drawers"} · dense {r.verdict_dense}, hybrid {r.verdict_hybrid}
                      </span>
                      {r.hybrid
                        .filter((h) => !dense.has(h.chunk_id))
                        .map((h) => (
                          <span key={`+${h.chunk_id}`} className="diff add">
                            + {h.title} {h.label ?? `p. ${h.page}`}
                          </span>
                        ))}
                      {r.dense
                        .filter((h) => !hybrid.has(h.chunk_id))
                        .map((h) => (
                          <span key={`-${h.chunk_id}`} className="diff drop">
                            − {h.title} {h.label ?? `p. ${h.page}`}
                          </span>
                        ))}
                    </span>
                  </li>
                );
              })}
          </ul>
        </>
      )}
    </section>
  );
}
