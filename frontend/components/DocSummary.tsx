import type { DocumentRow } from "@/lib/api";

type Summarised = Pick<DocumentRow, "summary" | "concepts" | "enrich_status" | "enrich_error">;

/** The reader's "what this file covers": generated summary and key concepts, labelled as generated. */
export function DocSummary({ doc }: { doc: Summarised }) {
  if (doc.enrich_status === "skipped") return null;
  if (doc.enrich_status === "error")
    return <p className="muted doc-summary-note">No summary: {doc.enrich_error ?? "the model's reply wasn't usable"}.</p>;
  if (!doc.summary) return <p className="muted doc-summary-note">Summarising… it appears here within a few minutes.</p>;
  return (
    <section className="doc-summary" aria-label="What this file covers">
      <p dir="auto">
        {doc.summary}
        <span className="gen-tag" title="Written by the local model from this file; it can be wrong">
          generated
        </span>
      </p>
      {doc.concepts && doc.concepts.length > 0 && (
        <ul className="concepts" aria-label="Key concepts">
          {doc.concepts.map((c) => (
            <li key={c} dir="auto">
              {c}
            </li>
          ))}
        </ul>
      )}
      {doc.enrich_status === "pending" && <p className="muted">The file changed; a new summary is on its way.</p>}
    </section>
  );
}
