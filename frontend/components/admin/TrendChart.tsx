"use client";

import { useState } from "react";
import type { InsightsSummary } from "@/lib/api";

const W = 640;
const H = 96;
const PAD = { l: 40, r: 8, t: 8, b: 4 };
const GAP = 2; // surface gap between adjacent bars
const R = 4; // rounded data end, flat at the baseline

type Day = { day: string; questions: number; median_ms: number | null };

/** Every calendar day from start to end inclusive, as YYYY-MM-DD in the browser's time zone. */
function daysBetween(start: string, end: string): string[] {
  const out: string[] = [];
  const d = new Date(`${start}T12:00:00`);
  const stop = new Date(`${end}T12:00:00`);
  while (d <= stop) {
    out.push(d.toLocaleDateString("en-CA"));
    d.setDate(d.getDate() + 1);
  }
  return out;
}

const fmtDay = (day: string) => new Date(`${day}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const secs = (ms: number | null) => (ms === null ? "–" : `${(ms / 1000).toFixed(1)} s`);

/** A bar rising from the baseline with a 4px rounded top. */
function barPath(x: number, w: number, y: number, base: number): string {
  const r = Math.min(R, w / 2, base - y);
  return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${base}Z`;
}

/** One small multiple: a titled bar chart over the shared day axis, with its own single y-scale. */
function Panel({
  title,
  series,
  value,
  format,
  hover,
  onHover,
}: {
  title: string;
  series: Day[];
  value: (d: Day) => number | null;
  format: (v: number) => string;
  hover: number | null;
  onHover: (i: number | null) => void;
}) {
  const max = Math.max(1, ...series.map((d) => value(d) ?? 0));
  const iw = W - PAD.l - PAD.r;
  const base = H - PAD.b;
  const bw = iw / series.length;
  const y = (v: number) => base - (v / max) * (base - PAD.t);
  return (
    <div className="panel">
      <p className="panel-title">{title}</p>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}, ${fmtDay(series[0].day)} to ${fmtDay(series.at(-1)!.day)}`}>
        <line className="grid" x1={PAD.l} x2={W - PAD.r} y1={PAD.t} y2={PAD.t} />
        <line className="axis" x1={PAD.l} x2={W - PAD.r} y1={base} y2={base} />
        <text className="tick" x={PAD.l - 6} y={PAD.t + 4} textAnchor="end">
          {format(max)}
        </text>
        {series.map((d, i) => {
          const v = value(d);
          const x = PAD.l + i * bw + GAP / 2;
          return (
            <g key={d.day}>
              {hover === i && <rect className="hover-col" x={PAD.l + i * bw} y={PAD.t} width={bw} height={base - PAD.t} />}
              {v !== null && v > 0 && <path className="bar" d={barPath(x, Math.max(1, bw - GAP), y(v), base)} />}
              {/* hit target: the whole column, bigger than the mark */}
              <rect
                className="hit"
                x={PAD.l + i * bw}
                y={0}
                width={bw}
                height={H}
                onMouseEnter={() => onHover(i)}
                onMouseLeave={() => onHover(null)}
              />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Questions per day and median answer time as two small multiples over one day axis (never a dual axis). */
export function TrendChart({ days, data }: { days: number; data: InsightsSummary["per_day"] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (data.length === 0) return <p className="muted">No questions in this period.</p>;

  const today = new Date().toLocaleDateString("en-CA");
  const first = new Date();
  first.setDate(first.getDate() - (days - 1));
  const start = days > 0 ? first.toLocaleDateString("en-CA") : data[0].day;
  const byDay = new Map(data.map((d) => [d.day, d]));
  const series: Day[] = daysBetween(start, today).map((day) => byDay.get(day) ?? { day, questions: 0, median_ms: null });
  const h = hover === null ? null : series[hover];

  return (
    <figure className="trend">
      <p className="trend-readout" aria-live="polite">
        {h ? (
          <>
            <strong>{fmtDay(h.day)}</strong> · {h.questions} question{h.questions === 1 ? "" : "s"} · median {secs(h.median_ms)}
          </>
        ) : (
          <span className="muted">Point at a day for its numbers.</span>
        )}
      </p>
      <Panel
        title="Questions per day"
        series={series}
        value={(d) => d.questions}
        format={(v) => String(v)}
        hover={hover}
        onHover={setHover}
      />
      <Panel
        title="Median answer time"
        series={series}
        value={(d) => (d.median_ms === null ? null : d.median_ms / 1000)}
        format={(v) => `${v.toFixed(0)} s`}
        hover={hover}
        onHover={setHover}
      />
      <p className="trend-axis">
        <span>{fmtDay(series[0].day)}</span>
        <span>{fmtDay(today)}</span>
      </p>
      <details className="trend-table">
        <summary>Show as table</summary>
        <table className="admin-table">
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col">Questions</th>
              <th scope="col">Median answer time</th>
            </tr>
          </thead>
          <tbody>
            {series
              .filter((d) => d.questions > 0)
              .map((d) => (
                <tr key={d.day}>
                  <th scope="row">{fmtDay(d.day)}</th>
                  <td>{d.questions}</td>
                  <td>{secs(d.median_ms)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
