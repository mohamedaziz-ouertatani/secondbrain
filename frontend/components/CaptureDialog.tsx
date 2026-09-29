"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CaptureLine } from "@/components/planner/CaptureLine";
import { fetchModules, type PlannerItem, plannerHref } from "@/lib/planner";
import { useDrawer } from "@/lib/useLibrary";

function typing(t: EventTarget | null): boolean {
  return t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
}

/** Quick capture from any page: N (outside text fields) or Alt+N anywhere. Pre-fills the open drawer. */
export function CaptureDialog() {
  const drawer = useDrawer();
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [modules, setModules] = useState<string[]>([]);
  const [saved, setSaved] = useState<PlannerItem | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.repeat || e.code !== "KeyN") return;
      if (e.altKey || (!e.shiftKey && !typing(e.target))) {
        e.preventDefault();
        setOpen(true);
        fetchModules().then(setModules).catch(() => {});
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (open && !d.open) d.showModal(); // modal: traps focus, Esc closes, focus returns on close
    if (!open && d.open) d.close();
  }, [open]);

  useEffect(() => {
    if (!saved) return;
    const t = window.setTimeout(() => setSaved(null), 5000);
    return () => window.clearTimeout(t);
  }, [saved]);

  return (
    <>
      <dialog ref={dialog} className="capture-dialog card" aria-label="Quick capture" onClose={() => setOpen(false)}>
        {open && (
          <CaptureLine
            drawer={drawer}
            modules={modules}
            autoFocus
            onSaved={(item) => {
              setSaved(item);
              setOpen(false);
            }}
          />
        )}
        <p className="capture-hint muted">Esc closes</p>
      </dialog>
      {saved && (
        <div className="undo-note" role="status" aria-live="polite">
          <span>Saved</span>
          <Link className="quiet-btn" href={plannerHref(saved.id, drawer)} onClick={() => setSaved(null)}>
            View
          </Link>
        </div>
      )}
    </>
  );
}
