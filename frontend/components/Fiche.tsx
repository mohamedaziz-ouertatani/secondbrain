"use client";

import { ExternalLink, RotateCcw, BookOpen } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { NoteProse } from "@/components/Prose";
import { callNumber, type Citation, fileUrl, readerUrl } from "@/lib/api";
import { excerpt, withoutLeadingTitle } from "@/lib/markdown";
import { tintVar } from "@/lib/modules";

/** A cited source as a catalogue card: call number, locator, snippet; flips to the full passage. */
export function Fiche({
  c,
  active,
  onActive,
}: {
  c: Citation;
  active: boolean;
  onActive: (n: number | null) => void;
}) {
  const [flipped, setFlipped] = useState(false);

  return (
    <article
      id={`fiche-${c.n}`}
      className={`fiche${active ? " pulled" : ""}${flipped ? " flipped" : ""}`}
      style={{ "--tint": tintVar(c.course) } as React.CSSProperties}
      onMouseEnter={() => onActive(c.n)}
      onMouseLeave={() => onActive(null)}
      onFocus={() => onActive(c.n)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) onActive(null);
      }}
    >
      <header className="fiche-head">
        <span className="fiche-n">{c.n}</span>
        <span className="callno">{callNumber(c)}</span>
        {c.ocr && (
          <span className="ocr-tag" title="Read from an image; may contain recognition errors">
            OCR
          </span>
        )}
      </header>

      {flipped ? (
        <div className="fiche-back" dir="auto">
          <NoteProse text={withoutLeadingTitle(c.text)} />
        </div>
      ) : (
        <div className="fiche-front">
          <h3 className="fiche-title" dir="auto">
            {c.title}
          </h3>
          <p className="fiche-snippet" dir="auto">
            {excerpt(c.text || c.snippet)}
          </p>
        </div>
      )}

      <footer className="fiche-actions">
        <button type="button" className="icon-btn" onClick={() => setFlipped((f) => !f)} aria-pressed={flipped}>
          <RotateCcw size={15} aria-hidden />
          {flipped ? "Front" : "Passage"}
        </button>
        <Link className="icon-btn" href={readerUrl(c.doc_id, c.page)}>
          <BookOpen size={15} aria-hidden />
          Read
        </Link>
        <a className="icon-btn" href={fileUrl(c)} target="_blank" rel="noreferrer" title="Open the original file">
          <ExternalLink size={15} aria-hidden />
          Original
        </a>
      </footer>
    </article>
  );
}
