"use client";

import { ExternalLink, PenLine } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DocSummary } from "@/components/DocSummary";
import { NoteProse } from "@/components/Prose";
import {
  callNumber,
  type DocumentPages,
  fileUrl,
  getJSON,
  kindOf,
  locator,
  pageImageUrl,
  partsCount,
  PDF,
} from "@/lib/api";
import { withoutLeadingTitle } from "@/lib/markdown";
import { tintVar, unitOf } from "@/lib/modules";
import { markSeen } from "@/lib/seen";
import { drawerHref } from "@/lib/useLibrary";

/** Read a filed document page by page, the way it was indexed. */
export default function ReaderPage() {
  const { id } = useParams<{ id: string }>();
  const [doc, setDoc] = useState<DocumentPages | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const docId = Number(id);
    getJSON<DocumentPages>(`/documents/${docId}/pages`)
      .then((d) => {
        setDoc(d);
        markSeen(docId);
      })
      .catch(() => setError("This fiche couldn't be opened. The file may have moved; rescan the inbox."));
  }, [id]);

  useEffect(() => {
    if (!doc || !location.hash) return;
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [doc]);

  if (error) return <p className="notice bad">{error}</p>;
  if (!doc)
    return (
      <div className="skeleton reader-skeleton" aria-label="Loading">
        <span />
        <span />
        <span />
      </div>
    );

  const markdown = doc.mime === "text/markdown";
  const parts = partsCount(doc.mime, doc.page_count);
  return (
    <div className="reader" style={{ "--tint": tintVar(doc.course) } as React.CSSProperties}>
      <header className="card reader-head">
        <p className="callno">{callNumber({ ...doc, page: 0, mime: "" })}</p>
        <h1 dir="auto">{doc.title}</h1>
        <p className="reader-meta">
          {doc.course ? `${doc.course} · ${unitOf(doc.course).name}` : "Loose note"} · {kindOf(doc.mime)}
          {parts ? ` · ${parts}` : ""}
        </p>
        <DocSummary doc={doc} />
        <div className="reader-actions">
          <Link className="quiet-btn" href={drawerHref("/", doc.course)}>
            <PenLine size={15} aria-hidden />
            Ask {doc.course ?? "all drawers"}
          </Link>
          <a className="quiet-btn" href={fileUrl({ doc_id: doc.id, mime: doc.mime })} target="_blank" rel="noreferrer">
            <ExternalLink size={15} aria-hidden />
            Open the original
          </a>
        </div>
        {doc.status !== "ok" && (
          <p className="notice">
            {doc.status === "empty_text"
              ? "This file has no text layer (it looks scanned), so it isn't searchable yet."
              : `This file couldn't be read: ${doc.error ?? "unknown error"}.`}
          </p>
        )}
      </header>

      {doc.pages.map((p) => (
        <section key={p.page} id={`p-${p.page}`} className="card page">
          {doc.pages.length > 1 && (
            <p className="page-label">
              {doc.mime === PDF ? (
                <a href={fileUrl({ doc_id: doc.id, mime: doc.mime, page: p.page })} target="_blank" rel="noreferrer">
                  {locator({ ...doc, page: p.page, label: p.label })}
                </a>
              ) : (
                locator({ ...doc, page: p.page, label: p.label })
              )}
            </p>
          )}
          {doc.mime === PDF ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element -- served by the API, not Next's image pipeline */}
              <img
                className="page-image"
                src={pageImageUrl(doc.id, p.page)}
                alt={p.text.trim() ? `Page ${p.page}` : `Page ${p.page}, no text layer`}
                loading="lazy"
              />
              {p.text.trim() && (
                <details className="page-text">
                  <summary>Indexed text</summary>
                  <div className="plain" dir="auto">
                    {p.text}
                  </div>
                </details>
              )}
            </>
          ) : p.text.trim() ? (
            markdown ? (
              <div className="prose" dir="auto">
                <NoteProse text={p.page === 1 ? withoutLeadingTitle(p.text) : p.text} docId={doc.id} />
              </div>
            ) : (
              <div className="plain" dir="auto">
                {p.text}
              </div>
            )
          ) : (
            <p className="muted">No text on this {doc.mime === PDF ? "page" : "part"}.</p>
          )}
        </section>
      ))}
    </div>
  );
}
