"use client";

import { Eye, FolderInput, NotebookPen, PenLine } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { NoteProse } from "@/components/Prose";
import { plannerHref } from "@/lib/planner";
import type { SaveState, useScratchpad } from "@/lib/useScratchpad";
import { tintVar } from "@/lib/modules";

const STATE_LABEL: Record<SaveState, string> = {
  loading: "Opening…",
  idle: "",
  unsaved: "Editing…",
  saving: "Saving…",
  saved: "Saved",
  error: "Not saved",
};

/** The drawer's scratchpad beside the answer: clips land here, and it files into the drawer as a note. */
export function Scratchpad({ drawer, pad }: { drawer: string | null; pad: ReturnType<typeof useScratchpad> }) {
  const [preview, setPreview] = useState(false);
  const { body, setBody, item, state, file, filed, fileError } = pad;
  const empty = !body.trim();

  return (
    <aside className="card scratch" aria-label="Scratchpad" style={{ "--tint": tintVar(drawer) } as React.CSSProperties}>
      <header className="scratch-head">
        <h2>
          <NotebookPen size={15} aria-hidden />
          Scratchpad
        </h2>
        <span className={`scratch-state${state === "error" ? " bad" : ""}`} aria-live="polite">
          {STATE_LABEL[state]}
        </span>
        <button
          type="button"
          className="icon-btn"
          aria-pressed={preview}
          onClick={() => setPreview((p) => !p)}
          title={preview ? "Back to editing" : "Show it rendered, formulas and all"}
        >
          {preview ? <PenLine size={14} aria-hidden /> : <Eye size={14} aria-hidden />}
          {preview ? "Edit" : "Preview"}
        </button>
      </header>

      {preview ? (
        <div className="scratch-preview" dir="auto">
          {empty ? <p className="scratch-hint">Nothing here yet.</p> : <NoteProse text={body} />}
        </div>
      ) : (
        <>
          <label htmlFor="scratch-text" className="sr-only">
            Scratchpad for {drawer ?? "all drawers"}
          </label>
          <textarea
            id="scratch-text"
            className="scratch-text"
            dir="auto"
            value={body}
            disabled={state === "loading"}
            placeholder="Select text in the answer and press Clip, or clip a fiche. Type anything too; it saves as you go."
            onChange={(e) => setBody(e.target.value)}
          />
        </>
      )}

      {state === "error" && <p className="notice bad">Couldn&apos;t save the scratchpad. Is the backend running?</p>}
      {fileError && <p className="notice bad">{fileError}</p>}
      {filed && (
        <p className="notice">
          Filed as <code>{filed.filed_path}</code>. The next clip starts a fresh scratchpad.
        </p>
      )}

      <footer className="scratch-foot">
        {item && (
          <Link className="icon-btn" href={plannerHref(item.id, drawer)}>
            Open in Planner
          </Link>
        )}
        {drawer ? (
          <button
            type="button"
            className="quiet-btn"
            disabled={empty || state === "loading" || state === "error"}
            onClick={file}
            title={`Save it as a note in ${drawer}, where the search can find it`}
          >
            <FolderInput size={15} aria-hidden />
            File into drawer
          </button>
        ) : (
          <span className="scratch-hint">Pick a drawer to file it.</span>
        )}
      </footer>
    </aside>
  );
}
