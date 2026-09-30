"use client";

import "katex/dist/katex.min.css";
import type { ComponentProps } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { noteAssetUrl } from "@/lib/api";
import { rehypeClaims } from "@/lib/claims";
import { normaliseMath, prepareAnswer, relativeImagePath } from "@/lib/markdown";

type CiteProps = {
  /** Citation numbers that resolve to a fiche; others render as plain numerals. */
  known: Set<number>;
  active: number | null;
  onActive: (n: number | null) => void;
  onPull: (n: number) => void;
};

const REMARK = [remarkGfm, remarkMath];
const REHYPE = [[rehypeKatex, { throwOnError: false, strict: "ignore" }]] as ComponentProps<
  typeof ReactMarkdown
>["rehypePlugins"];
const ANSWER_REHYPE = [...(REHYPE ?? []), rehypeClaims] as typeof REHYPE;

/**
 * Answer text, split into claims by citation run: each claim carries its margin tab on the line
 * where its citation sits, and lights up when the fiche it leans on is focused.
 */
export function AnswerProse({ text, cite }: { text: string; cite: CiteProps }) {
  const components: Components = {
    h1: ({ children }) => <h3>{children}</h3>,
    h2: ({ children }) => <h3>{children}</h3>,
    span: ({ node, className, children, ...rest }) => {
      if (className !== "claim") {
        return (
          <span className={className} {...rest}>
            {children}
          </span>
        );
      }
      const nums = String(node?.properties?.dataCites ?? "")
        .split(",")
        .filter(Boolean)
        .map(Number)
        .filter((n) => cite.known.has(n));
      const traced = cite.active !== null && nums.includes(cite.active);
      return (
        <span className={traced ? "claim traced" : "claim"}>
          {children}
          {nums.length > 0 && (
            <span className="margin-tabs" aria-hidden>
              {nums.map((n) => (
                <span key={n} className={n === cite.active ? "tab on" : "tab"}>
                  {n}
                </span>
              ))}
            </span>
          )}
        </span>
      );
    },
    a: ({ href, children }) => {
      const m = href ? /^#cite-(\d+)$/.exec(href) : null;
      if (!m) {
        return (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        );
      }
      const n = Number(m[1]);
      if (!cite.known.has(n)) return <sup className="cite pending">{n}</sup>;
      return (
        <button
          type="button"
          className={n === cite.active ? "cite on" : "cite"}
          aria-label={`Source ${n}`}
          onMouseEnter={() => cite.onActive(n)}
          onMouseLeave={() => cite.onActive(null)}
          onFocus={() => cite.onActive(n)}
          onBlur={() => cite.onActive(null)}
          onClick={() => cite.onPull(n)}
        >
          {n}
        </button>
      );
    },
    table: ({ children }) => (
      <div className="table-scroll">
        <table>{children}</table>
      </div>
    ),
  };

  return (
    <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={ANSWER_REHYPE} components={components}>
      {prepareAnswer(text)}
    </ReactMarkdown>
  );
}

/**
 * Synced notes and passages: Markdown with LaTeX, links open outside. With `docId`, pictures the
 * note links by a relative path (saved beside it) are shown.
 */
export function NoteProse({ text, docId }: { text: string; docId?: number }) {
  return (
    <ReactMarkdown
      remarkPlugins={REMARK}
      rehypePlugins={REHYPE}
      components={{
        h1: ({ children }) => <h3>{children}</h3>,
        h2: ({ children }) => <h3>{children}</h3>,
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        ),
        table: ({ children }) => (
          <div className="table-scroll">
            <table>{children}</table>
          </div>
        ),
        img: ({ src, alt }) => {
          const rel = typeof src === "string" ? relativeImagePath(src) : null;
          const url =
            typeof src === "string" && /^https?:/i.test(src)
              ? src
              : rel !== null && docId !== undefined
                ? noteAssetUrl(docId, rel)
                : null;
          if (!url) return alt ? <span className="img-missing">[{alt}]</span> : null;
          // eslint-disable-next-line @next/next/no-img-element -- served by the API, not Next's image pipeline
          return <img className="note-image" src={url} alt={alt ?? ""} loading="lazy" />;
        },
      }}
    >
      {normaliseMath(text)}
    </ReactMarkdown>
  );
}
