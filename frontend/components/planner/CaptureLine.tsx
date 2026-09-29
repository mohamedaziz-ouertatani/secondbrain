"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  createItem,
  type Draft,
  fromLocalInput,
  type ItemFields,
  KIND_LABEL,
  type Kind,
  parseLine,
  type PlannerItem,
  readingLabel,
  type Span,
  toLocalDate,
  toLocalInput,
} from "@/lib/planner";

type Pin = Partial<Pick<Draft, "kind" | "course" | "starts_at" | "all_day">>;
const KINDS: Kind[] = ["note", "todo", "event"];

/** The typed text, with what the parser matched underlined (drawn behind the transparent-text input). */
function Marked({ text, spans }: { text: string; spans: Span[] }) {
  const out: React.ReactNode[] = [];
  let at = 0;
  for (const s of spans) {
    if (s.start < at) continue;
    out.push(text.slice(at, s.start));
    out.push(
      <mark key={s.start} className={`cap-${s.role}`}>
        {text.slice(s.start, s.end)}
      </mark>,
    );
    at = s.end;
  }
  out.push(text.slice(at));
  return <>{out}</>;
}

function fieldsOf(d: Draft): ItemFields & { kind: Kind } {
  if (d.kind === "note") return { kind: "note", title: d.title, course: d.course };
  if (d.kind === "todo") return { kind: "todo", title: d.title, course: d.course, starts_at: d.starts_at };
  return { kind: "event", title: d.title, course: d.course, starts_at: d.starts_at, ends_at: d.ends_at, all_day: d.all_day };
}

/**
 * One line to capture a note, to-do or event. The backend reads it as you type; the reading shows
 * underneath, and each part of it can be changed before Enter saves.
 */
export function CaptureLine({
  drawer,
  modules,
  onSaved,
  autoFocus = false,
}: {
  drawer: string | null;
  modules: string[];
  onSaved: (item: PlannerItem) => void;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pin, setPin] = useState<Pin>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mirror = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const readingId = useId();

  useEffect(() => {
    if (!text.trim()) return;
    const ctl = new AbortController();
    const t = window.setTimeout(() => {
      parseLine(text, drawer, ctl.signal)
        .then(setDraft)
        .catch(() => {});
    }, 250);
    return () => {
      window.clearTimeout(t);
      ctl.abort();
    };
  }, [text, drawer]);

  const reading = text.trim() && draft ? { ...draft, ...pin } : null;

  async function save() {
    const t = text.trim();
    if (!t || saving) return;
    setSaving(true);
    setError(null);
    // read the final text fresh: the shown reading may be from a few keystrokes ago
    const parsed = await Promise.race([
      parseLine(text, drawer).catch(() => null),
      new Promise<null>((r) => window.setTimeout(() => r(null), 1500)),
    ]);
    const fields = parsed ? fieldsOf({ ...parsed, ...pin }) : { kind: "note" as const, title: t, course: pin.course ?? drawer };
    try {
      const item = await createItem(fields);
      setText("");
      setDraft(null);
      setPin({});
      onSaved(item);
      input.current?.focus();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="capture">
      <div className="capture-field">
        <div className="capture-mirror" ref={mirror} aria-hidden>
          <Marked text={text} spans={reading ? draft?.matched ?? [] : []} />
        </div>
        <input
          ref={input}
          value={text}
          dir="auto"
          autoFocus={autoFocus}
          placeholder="Note, to-do or event… e.g. DEVOPS TP due fri 23:59"
          aria-label="Capture a note, to-do or event"
          aria-describedby={reading ? readingId : undefined}
          onChange={(e) => {
            setText(e.target.value);
            if (!e.target.value.trim()) setPin({});
          }}
          onScroll={(e) => {
            if (mirror.current) mirror.current.scrollLeft = e.currentTarget.scrollLeft;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              save();
            }
          }}
        />
      </div>

      {reading && (
        <div className="capture-reading" id={readingId}>
          <span className="callno">{readingLabel(reading)}</span>
          <div className="capture-controls">
            <div className="segmented" role="group" aria-label="Kind">
              {KINDS.map((k) => (
                <button
                  key={k}
                  type="button"
                  aria-pressed={reading.kind === k}
                  onClick={() => setPin((p) => ({ ...p, kind: k }))}
                >
                  {KIND_LABEL[k]}
                </button>
              ))}
            </div>
            <select
              aria-label="Drawer"
              value={reading.course ?? ""}
              onChange={(e) => setPin((p) => ({ ...p, course: e.target.value || null }))}
            >
              <option value="">No drawer</option>
              {modules.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            {reading.kind !== "note" && (
              <input
                type={reading.all_day ? "date" : "datetime-local"}
                aria-label={reading.kind === "todo" ? "Due" : "Starts"}
                value={reading.starts_at ? (reading.all_day ? toLocalDate(reading.starts_at) : toLocalInput(reading.starts_at)) : ""}
                onChange={(e) => setPin((p) => ({ ...p, starts_at: e.target.value ? fromLocalInput(e.target.value) : null }))}
              />
            )}
            {reading.kind === "event" && (
              <label className="plan-inline">
                <input
                  type="checkbox"
                  checked={reading.all_day}
                  onChange={(e) => setPin((p) => ({ ...p, all_day: e.target.checked }))}
                />{" "}
                All day
              </label>
            )}
          </div>
        </div>
      )}
      <p className="capture-hint muted">{saving ? "Saving…" : "Enter saves"}</p>
      {error && <p className="notice bad">{error}</p>}
    </div>
  );
}
