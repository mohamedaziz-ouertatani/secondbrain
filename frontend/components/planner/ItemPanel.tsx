"use client";

import { FolderInput, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { NoteProse } from "@/components/Prose";
import { readerUrl } from "@/lib/api";
import { tintVar } from "@/lib/modules";
import {
  announce,
  fileNote,
  fromLocalInput,
  type ItemFields,
  KIND_LABEL,
  type Kind,
  patchItem,
  type PlannerItem,
  toLocalDate,
  toLocalInput,
} from "@/lib/planner";
import { useLibrary } from "@/lib/useLibrary";

const KINDS: Kind[] = ["note", "todo", "event"];

function tomorrowNine(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  return d.toISOString();
}

/** Fields the other kinds don't allow, cleared when switching kind. */
function kindChange(item: PlannerItem, kind: Kind): ItemFields {
  if (kind === "note") return { kind, starts_at: null, ends_at: null, all_day: false };
  if (kind === "todo") return { kind, ends_at: null, all_day: false };
  return { kind, starts_at: item.starts_at ?? tomorrowNine(), done: false }; // events can't be done
}

/** Everything about one item. Each field saves when you leave it; Blackboard's fields are read-only. */
export function ItemPanel({
  item,
  modules,
  onClose,
  onDelete,
}: {
  item: PlannerItem;
  modules: string[];
  onClose: () => void;
  onDelete: (id: number) => void;
}) {
  const { docs, reload } = useLibrary();
  const [title, setTitle] = useState(item.title);
  const [body, setBody] = useState(item.body);
  const [preview, setPreview] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filing, setFiling] = useState(false);
  const bb = item.source === "blackboard";
  const locked = bb || !!item.filed_path; // kind and module
  const filedDoc = item.filed_path ? docs?.find((d) => d.path === item.filed_path) : undefined;
  const indexing = !!item.filed_path && !filedDoc;

  // the watcher indexes a filed note within seconds; check until the reader can open it
  useEffect(() => {
    if (!indexing) return;
    const t = window.setInterval(reload, 2000);
    return () => window.clearInterval(t);
  }, [indexing, reload]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function save(f: ItemFields) {
    setError(null);
    try {
      await patchItem(item.id, f);
    } catch (e) {
      setError((e as Error).message);
      announce(); // reload, so the panel shows what was actually saved
    }
  }

  async function file() {
    setFiling(true);
    setError(null);
    try {
      if (title !== item.title || body !== item.body) await patchItem(item.id, { title, body });
      await fileNote(item.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setFiling(false);
    }
  }

  const meta = [KIND_LABEL[item.kind].toUpperCase(), bb ? "FROM BLACKBOARD" : null, item.filed_path ? "FILED" : null]
    .filter(Boolean)
    .join(" · ");

  return (
    <aside
      className="plan-panel card"
      aria-label={`${KIND_LABEL[item.kind]}: ${item.title || "untitled"}`}
      style={{ "--tint": tintVar(item.course) } as React.CSSProperties}
    >
      <header className="plan-panel-head">
        <span className="callno">{meta}</span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={16} aria-hidden />
        </button>
      </header>

      <input
        className="plan-panel-title"
        value={title}
        readOnly={bb}
        dir="auto"
        aria-label="Title"
        placeholder={item.kind === "note" ? "Untitled note" : "Title"}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={() => title !== item.title && save({ title })}
      />

      <div className="plan-fields">
        <div className="segmented" role="group" aria-label="Kind">
          {KINDS.map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={item.kind === k}
              disabled={locked}
              onClick={() => k !== item.kind && save(kindChange(item, k))}
            >
              {KIND_LABEL[k]}
            </button>
          ))}
        </div>
        <select aria-label="Drawer" value={item.course ?? ""} disabled={locked} onChange={(e) => save({ course: e.target.value || null })}>
          <option value="">No drawer</option>
          {[...new Set([...modules, ...(item.course ? [item.course] : [])])].map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        {item.kind !== "note" && (
          <label className="plan-inline">
            {item.kind === "todo" ? "Due" : "Starts"}
            <input
              type={item.all_day ? "date" : "datetime-local"}
              readOnly={bb}
              value={item.starts_at ? (item.all_day ? toLocalDate(item.starts_at) : toLocalInput(item.starts_at)) : ""}
              onChange={(e) => save({ starts_at: e.target.value ? fromLocalInput(e.target.value) : null })}
            />
          </label>
        )}
        {item.kind === "event" && !item.all_day && (
          <label className="plan-inline">
            Ends
            <input
              type="datetime-local"
              value={item.ends_at ? toLocalInput(item.ends_at) : ""}
              onChange={(e) => save({ ends_at: e.target.value ? fromLocalInput(e.target.value) : null })}
            />
          </label>
        )}
        {item.kind === "event" && (
          <label className="plan-inline">
            <input type="checkbox" checked={item.all_day} onChange={(e) => save({ all_day: e.target.checked, ends_at: null })} /> All
            day
          </label>
        )}
        {item.kind !== "event" && (
          <label className="plan-inline">
            <input type="checkbox" checked={!!item.done_at} onChange={() => save({ done: !item.done_at })} /> Done
          </label>
        )}
      </div>
      {item.removed_at && <p className="notice">Blackboard no longer lists this. It&apos;s kept here in case you still need it.</p>}

      <div className="plan-body">
        <div className="segmented" role="group" aria-label="Body">
          <button type="button" aria-pressed={!preview} onClick={() => setPreview(false)}>
            Write
          </button>
          <button type="button" aria-pressed={preview} onClick={() => setPreview(true)}>
            Preview
          </button>
        </div>
        {preview ? (
          <div className="plan-preview">{body.trim() ? <NoteProse text={body} /> : <p className="muted">Nothing written yet.</p>}</div>
        ) : (
          <textarea
            value={body}
            dir="auto"
            rows={10}
            aria-label="Details (Markdown)"
            placeholder={item.kind === "note" ? "Write the note… Markdown and $formulas$ work." : "Details…"}
            onChange={(e) => setBody(e.target.value)}
            onBlur={() => body !== item.body && save({ body })}
          />
        )}
      </div>

      {error && <p className="notice bad">{error}</p>}

      <footer className="plan-panel-foot">
        {item.kind === "note" &&
          (item.filed_path ? (
            filedDoc ? (
              <Link className="quiet-btn" href={readerUrl(filedDoc.id)}>
                Filed · open in reader
              </Link>
            ) : (
              <span className="muted">Filed as {item.filed_path}. Indexing…</span>
            )
          ) : (
            <button
              type="button"
              className="quiet-btn"
              disabled={!item.course || filing}
              onClick={file}
              title={item.course ? undefined : "Pick a drawer first"}
            >
              <FolderInput size={15} aria-hidden /> {filing ? "Filing…" : "File into drawer"}
            </button>
          ))}
        <button type="button" className="quiet-btn delete" onClick={() => onDelete(item.id)}>
          <Trash2 size={15} aria-hidden /> Delete
        </button>
      </footer>
      {item.kind === "note" && !item.filed_path && (
        <p className="muted plan-panel-hint">Filing saves the note as Markdown in its drawer, so answers can cite it.</p>
      )}
    </aside>
  );
}
