"use client";

/** The undo slip after a delete; also reports a delete the backend refused. */
export function UndoNote({
  pending,
  failed,
  onUndo,
  what = "answer",
}: {
  pending: number | null;
  failed: boolean;
  onUndo: () => void;
  what?: string;
}) {
  if (pending === null && !failed) return <div className="undo-note" role="status" aria-live="polite" hidden />;
  return (
    <div className={`undo-note${failed ? " bad" : ""}`} role="status" aria-live="polite">
      {failed ? (
        <span>Couldn&apos;t delete that {what}. It&apos;s back in the list.</span>
      ) : (
        <>
          <span>{what.charAt(0).toUpperCase() + what.slice(1)} deleted</span>
          <button type="button" className="quiet-btn" onClick={onUndo}>
            Undo
          </button>
        </>
      )}
    </div>
  );
}
