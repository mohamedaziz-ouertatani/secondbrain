"use client";

import { ArrowUp, MessageSquareText, PanelRightClose } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AnswerCard, type Entry } from "@/components/AnswerCard";
import {
  askStream,
  type Citation,
  locator,
  putLabels,
  readerUrl,
} from "@/lib/api";

const OPEN_KEY = "sikimi.readerAsk.open";
// below this the panel would squeeze the page: it slides over it instead, closed until asked for
const SIDE_BY_SIDE = "(min-width: 1100px)";

type Scope = "file" | "course";

/** Side by side it opens as last left; over the page it waits to be asked for. Mounted client-side only. */
function initiallyOpen(): boolean {
  if (!window.matchMedia(SIDE_BY_SIDE).matches) return false;
  try {
    return localStorage.getItem(OPEN_KEY) !== "0";
  } catch {
    return true; // storage may be blocked
  }
}

/** Ask beside the reader: answers from the open file by default, or from its whole course. */
export function ReaderAsk({
  doc,
  onJump,
}: {
  doc: { id: number; course: string | null; mime: string };
  /** a citation into the open file: scroll the reader to that page or slide */
  onJump: (page: number) => void;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const [scope, setScope] = useState<Scope>("file");
  const [question, setQuestion] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const [labelError, setLabelError] = useState<string | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const abort = useRef<AbortController | null>(null);

  const focusOnOpen = useRef(false);

  // unmount mid-answer: stop the stream
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (open && focusOnOpen.current) input.current?.focus();
    focusOnOpen.current = false;
  }, [open]);

  function toggle(next: boolean) {
    setOpen(next);
    if (window.matchMedia(SIDE_BY_SIDE).matches) {
      try {
        localStorage.setItem(OPEN_KEY, next ? "1" : "0");
      } catch {
        /* storage may be blocked */
      }
    }
    focusOnOpen.current = next;
  }

  // over the page, the panel would hide the place it jumps to: step aside first
  function jump(page: number) {
    if (!window.matchMedia(SIDE_BY_SIDE).matches) setOpen(false);
    onJump(page);
  }

  const busy = entries.some(
    (e) => e.status === "searching" || e.status === "writing",
  );
  const update = (id: string, patch: (e: Entry) => Partial<Entry>) =>
    setEntries((all) =>
      all.map((e) => (e.id === id ? { ...e, ...patch(e) } : e)),
    );

  async function submit() {
    const q = question.trim();
    if (!q || busy) return;
    const id = crypto.randomUUID();
    const fileOnly = scope === "file" || !doc.course;
    setEntries((all) => [
      {
        id,
        question: q,
        course: doc.course,
        text: "",
        status: "searching",
        citations: [],
        valid: null,
        startedAt: Date.now(),
      },
      ...all,
    ]);
    setActiveCite(null);
    setQuestion("");
    if (input.current) input.current.style.height = "auto";
    abort.current = new AbortController();
    await askStream(
      q,
      doc.course,
      {
        onToken: (t) =>
          update(id, (e) => ({ text: e.text + t, status: "writing" })),
        onDone: (d) =>
          update(id, () => ({
            text: d.answer,
            citations: d.citations,
            valid: d.citation_valid,
            status: "done",
            logId: d.log_id ?? undefined,
            endedAt: Date.now(),
          })),
        onError: (msg) =>
          update(id, () => ({
            status: "error",
            error: msg,
            endedAt: Date.now(),
          })),
      },
      abort.current.signal,
      fileOnly ? doc.id : undefined,
    );
  }

  async function rate(entry: Entry, v: -1 | 1 | null) {
    if (!entry.logId) return;
    const before = entry.feedback;
    setLabelError(null);
    update(entry.id, () => ({ feedback: v }));
    try {
      await putLabels(entry.logId, { feedback: v });
    } catch {
      update(entry.id, () => ({ feedback: before }));
      setLabelError("Couldn't save your mark. Is the backend running?");
    }
  }

  function follow(entry: Entry, n: number) {
    const c = entry.citations.find((x) => x.n === n);
    if (c && c.doc_id === doc.id) jump(c.page);
  }

  if (!open)
    return (
      <button
        type="button"
        className="reader-ask-tab"
        onClick={() => toggle(true)}
        aria-label="Ask about this file"
      >
        <MessageSquareText size={16} aria-hidden />
        <span>Ask</span>
      </button>
    );

  return (
    <aside className="reader-ask" aria-label="Ask about this file">
      <header className="reader-ask-head">
        <h2>Ask</h2>
        {doc.course && (
          <div className="scope" role="radiogroup" aria-label="Answer from">
            {(["file", "course"] as const).map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={scope === s}
                onClick={() => setScope(s)}
              >
                {s === "file" ? "This file" : doc.course}
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          className="icon-btn"
          onClick={() => toggle(false)}
          aria-label="Hide the ask panel"
        >
          <PanelRightClose size={16} aria-hidden />
        </button>
      </header>

      <form
        className="reader-ask-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label htmlFor="reader-q" className="sr-only">
          Your question
        </label>
        <textarea
          id="reader-q"
          ref={input}
          dir="auto"
          rows={2}
          value={question}
          placeholder={
            scope === "file" || !doc.course
              ? "Ask about this file…"
              : `Ask ${doc.course}…`
          }
          onChange={(e) => {
            setQuestion(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${e.target.scrollHeight}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button
          type="submit"
          className="ask-btn"
          disabled={busy || !question.trim()}
        >
          <ArrowUp size={16} aria-hidden />
          Ask
        </button>
      </form>

      <div className="reader-ask-answers">
        {entries.length === 0 && (
          <p className="fiches-empty">
            Ask while you read. Answers cite the slides and pages they come
            from; click one to go to it.
          </p>
        )}
        {entries.map((e, i) => (
          <div key={e.id} className="reader-answer">
            <AnswerCard
              entry={e}
              activeCite={i === 0 ? activeCite : null}
              onActiveCite={i === 0 ? setActiveCite : () => {}}
              onPull={(n) => follow(e, n)}
              onRate={e.logId ? (v) => rate(e, v) : undefined}
              labelError={i === 0 ? labelError : null}
            />
            {e.citations.length > 0 && (
              <Sources citations={e.citations} docId={doc.id} onJump={jump} />
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}

/** Where the answer comes from: a place in this file scrolls the reader, another file opens it. */
function Sources({
  citations,
  docId,
  onJump,
}: {
  citations: Citation[];
  docId: number;
  onJump: (page: number) => void;
}) {
  return (
    <ol className="reader-sources">
      {citations.map((c) => (
        <li key={c.n}>
          <span className="n">[{c.n}]</span>
          {c.doc_id === docId ? (
            <button
              type="button"
              className="linkish"
              onClick={() => onJump(c.page)}
            >
              {locator(c)}
            </button>
          ) : (
            <Link href={readerUrl(c.doc_id, c.page)}>
              {c.title} · {locator(c)}
            </Link>
          )}
        </li>
      ))}
    </ol>
  );
}
