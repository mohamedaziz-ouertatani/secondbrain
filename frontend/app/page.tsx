"use client";

import { ArrowUp } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { AnswerCard, type Entry, PastCard } from "@/components/AnswerCard";
import { ComingUp } from "@/components/ComingUp";
import { DrawerDigest } from "@/components/DrawerDigest";
import { Fiche } from "@/components/Fiche";
import { Scratchpad } from "@/components/Scratchpad";
import { UndoNote } from "@/components/UndoNote";
import { askStream, callNumber, fetchHistory, fetchHistoryItem, putLabels } from "@/lib/api";
import { toEntry, useUndoDelete } from "@/lib/history";
import { withoutLeadingTitle } from "@/lib/markdown";
import { tintVar } from "@/lib/modules";
import { clipBlock } from "@/lib/scratchpad.ts";
import { useDrawer, useLibrary } from "@/lib/useLibrary";
import { useScratchpad } from "@/lib/useScratchpad";

const LEGACY_HISTORY_KEY = "sb.history.v1"; // browser-only history from before the server kept it
const DESK_HISTORY = 40;

function AskDesk() {
  const drawer = useDrawer();
  const { docs } = useLibrary();
  const [question, setQuestion] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const openParam = useSearchParams().get("open");
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const { hidden, remove, undo, pending, failed } = useUndoDelete();
  const pad = useScratchpad(drawer);

  useEffect(() => {
    try {
      localStorage.removeItem(LEGACY_HISTORY_KEY);
    } catch {
      /* storage may be blocked */
    }
    const ctl = new AbortController();
    fetchHistory({ limit: DESK_HISTORY }, ctl.signal)
      .then((items) => {
        // keep anything asked while this was loading; it isn't in the list yet
        setEntries((live) => [...live.filter((e) => !e.logId), ...items.map(toEntry)]);
        setLoaded(true);
      })
      .catch((e) => {
        if (e?.name !== "AbortError") {
          setLoadError(true);
          setLoaded(true);
        }
      });
    return () => ctl.abort();
  }, []);

  // /?open=<id> (from the History page): bring that message to the front. It is fetched on its own
  // because it may be older than the desk's 40; one small request is simpler than checking first.
  useEffect(() => {
    const id = Number(openParam);
    if (!openParam || !loaded || !Number.isInteger(id)) return;
    let cancelled = false;
    fetchHistoryItem(id)
      .then((h) => {
        if (cancelled) return;
        setEntries((cur) => (cur.some((e) => e.logId === id) ? cur : [toEntry(h), ...cur]));
        setActiveId(String(id));
        setActiveCite(null);
      })
      .catch(() => {}); // deleted meanwhile: the desk just shows its usual front card
    return () => {
      cancelled = true;
    };
  }, [openParam, loaded]);

  const shown = entries.filter((e) => !(e.logId && hidden.has(e.logId)));
  const inDrawer = shown.filter((e) => drawer === null || e.course === drawer);
  // activeId is a client id for answers asked here, or a query_log id when opened from History
  const active = inDrawer.find((e) => e.id === activeId || String(e.logId) === activeId) ?? inDrawer[0] ?? null;
  const past = inDrawer.filter((e) => e !== active);
  const busy = entries.some((e) => e.status === "searching" || e.status === "writing");

  const update = (id: string, patch: (e: Entry) => Partial<Entry>) =>
    setEntries((all) => all.map((e) => (e.id === id ? { ...e, ...patch(e) } : e)));

  // Labels (answer rating, relevant fiches) are saved at once; shown optimistically, undone if saving fails.
  const [labelError, setLabelError] = useState<string | null>(null);
  async function saveLabels(entry: Entry, patch: Partial<Entry>, body: Parameters<typeof putLabels>[1]) {
    if (!entry.logId) return;
    const before = { feedback: entry.feedback, relevant: entry.relevant };
    setLabelError(null);
    update(entry.id, () => patch);
    try {
      await putLabels(entry.logId, body);
    } catch {
      update(entry.id, () => before);
      setLabelError("Couldn't save your mark. Is the backend running?");
    }
  }
  const rate = (entry: Entry, v: -1 | 1 | null) => saveLabels(entry, { feedback: v }, { feedback: v });
  function markRelevant(entry: Entry, n: number, v: boolean | null) {
    const relevant = { ...(entry.relevant ?? {}) };
    if (v === null) delete relevant[String(n)];
    else relevant[String(n)] = v;
    return saveLabels(entry, { relevant }, { relevant: { [String(n)]: v } });
  }

  async function submit() {
    const q = question.trim();
    if (!q || busy) return;
    const id = crypto.randomUUID();
    setEntries((all) => [
      { id, question: q, course: drawer, text: "", status: "searching", citations: [], valid: null, startedAt: Date.now() },
      ...all,
    ]);
    setActiveId(id);
    setActiveCite(null);
    setQuestion("");
    await askStream(q, drawer, {
      onToken: (t) => update(id, (e) => ({ text: e.text + t, status: "writing" })),
      onDone: (d) =>
        update(id, () => ({
          text: d.answer,
          citations: d.citations,
          valid: d.citation_valid,
          status: "done",
          logId: d.log_id ?? undefined,
          endedAt: Date.now(),
        })),
      onError: (msg) => update(id, () => ({ status: "error", error: msg, endedAt: Date.now() })),
    });
  }

  // a clip credits the fiches its claims cite, or the question when it cites none
  function clipAnswer(entry: Entry, text: string, cites: number[]) {
    const sources = cites.flatMap((n) => entry.citations.filter((c) => c.n === n).map(callNumber));
    pad.append(clipBlock(text, sources.length ? sources : [`asked: ${entry.question}`]));
  }

  const pull = useCallback((n: number) => {
    const el = document.getElementById(`fiche-${n}`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    (el?.querySelector("button, a") as HTMLElement | null)?.focus({ preventScroll: true });
  }, []);

  return (
    <div className="desk">
      <div className="stack">
        <form
          className="card working"
          style={{ "--tint": tintVar(drawer) } as React.CSSProperties}
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <label htmlFor="q" className="sr-only">
            Your question
          </label>
          <div className="header-line">
            <textarea
              id="q"
              ref={input}
              dir="auto"
              rows={1}
              value={question}
              placeholder={drawer ? `Ask ${drawer}…` : "Ask any drawer…"}
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
              autoFocus
            />
            <button type="submit" className="ask-btn" disabled={busy || !question.trim()}>
              <ArrowUp size={16} aria-hidden />
              Ask
            </button>
          </div>
          <p className="working-foot">
            <span>{drawer ? `Filed under ${drawer}` : "Searching all drawers"}</span>
            <span>Enter to ask · Shift+Enter for a new line</span>
          </p>
        </form>

        {active ? (
          <AnswerCard
            entry={active}
            activeCite={activeCite}
            onActiveCite={setActiveCite}
            onPull={pull}
            onDelete={active.logId ? () => remove(active.logId!) : undefined}
            onRate={active.logId ? (v) => rate(active, v) : undefined}
            onClip={(text, cites) => clipAnswer(active, text, cites)}
            labelError={labelError}
          />
        ) : (
          <DrawerDigest docs={docs} drawer={drawer} />
        )}

        <ComingUp drawer={drawer} />

        {past.length > 0 && (
          <section className="past-stack" aria-label="Earlier questions">
            <h2 className="stack-label">Earlier in this drawer</h2>
            {past.map((e, i) => (
              <PastCard
                key={e.id}
                entry={e}
                depth={Math.min(i, 4)}
                onOpen={() => {
                  setActiveId(e.id);
                  setActiveCite(null);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                onDelete={e.logId ? () => remove(e.logId!) : undefined}
              />
            ))}
          </section>
        )}
        {loadError && <p className="notice bad">Couldn&apos;t load your earlier questions. Is the backend running?</p>}
      </div>

      <div className="side">
        <aside className="fiches" aria-label="Cited fiches">
          {active && active.citations.length > 0 ? (
            active.citations.map((c) => (
              <Fiche
                key={c.n}
                c={c}
                active={activeCite === c.n}
                onActive={setActiveCite}
                relevant={active.relevant?.[String(c.n)]}
                onRelevant={active.logId && active.status === "done" ? (v) => markRelevant(active, c.n, v) : undefined}
                onClip={() => pad.append(clipBlock(withoutLeadingTitle(c.text || c.snippet), [callNumber(c)]))}
              />
            ))
          ) : (
            <p className="fiches-empty">
              {active?.status === "searching" || active?.status === "writing"
                ? "The fiches this answer cites will be pulled here."
                : "Cited fiches are pulled here, each with its call number and page."}
            </p>
          )}
        </aside>

        <Scratchpad drawer={drawer} pad={pad} />
      </div>

      <UndoNote pending={pending} failed={failed} onUndo={undo} />
    </div>
  );
}

export default function AskPage() {
  return (
    <Suspense>
      <AskDesk />
    </Suspense>
  );
}
