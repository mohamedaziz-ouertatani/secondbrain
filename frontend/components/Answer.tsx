"use client";

import { Fragment, useState } from "react";
import { type Citation, fileUrl, locator } from "@/lib/api";

export type Entry = {
  id: number;
  question: string;
  course: string | null;
  text: string;
  status: "streaming" | "done" | "error";
  citations: Citation[];
  valid: boolean | null;
  error?: string;
};

const CITE = /(\[\d+\])/;
const BOLD = /(\*\*[^*\n]+\*\*)/;

function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(BOLD).map((part, i) =>
        BOLD.test(part) ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
      )}
    </>
  );
}

export function Answer({ entry }: { entry: Entry }) {
  const [active, setActive] = useState<number | null>(null);
  const byN = new Map(entry.citations.map((c) => [c.n, c]));
  const final = entry.status === "done";

  return (
    <article className="qa" aria-busy={entry.status === "streaming"}>
      <h2 className="question" dir="auto">{entry.question}</h2>
      {entry.course && <p className="scope">Searched in {entry.course}</p>}

      <div className="answer" dir="auto">
        {entry.text.split(CITE).map((part, i) => {
          const m = /^\[(\d+)\]$/.exec(part);
          if (!m) return <Inline key={i} text={part} />;
          const c = final ? byN.get(Number(m[1])) : undefined;
          if (!c) return <span key={i} className="mark pending">{m[1]}</span>;
          return (
            <a
              key={i}
              className="mark"
              href={fileUrl(c)}
              target="_blank"
              rel="noreferrer"
              title={`${c.title}, ${locator(c)}`}
              onMouseEnter={() => setActive(c.n)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(c.n)}
              onBlur={() => setActive(null)}
            >
              {c.n}
            </a>
          );
        })}
        {entry.status === "streaming" && <span className="caret" aria-hidden />}
      </div>

      {entry.status === "error" && <p className="notice error">{entry.error}</p>}
      {final && entry.valid === false && (
        <p className="notice">
          This answer doesn&apos;t cite your notes properly. Check it against the sources before relying on it.
        </p>
      )}

      {entry.citations.length > 0 && (
        <ol className="sources">
          {entry.citations.map((c) => (
            <li key={c.n} className={active === c.n ? "active" : undefined}>
              <a href={fileUrl(c)} target="_blank" rel="noreferrer">
                <span className="num">{c.n}</span>
                <span className={c.mime === "application/pdf" || !c.label ? "page" : "page section"} dir="auto">
                  {locator(c)}
                </span>
                <span className="meta">
                  <span className="title" dir="auto">{c.title}</span>
                  {c.course && <span className="course">{c.course}</span>}
                  <span className="snippet" dir="auto">{c.snippet}</span>
                </span>
              </a>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}
