"use client";

import { ArrowUp } from "lucide-react";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { AnswerCard, type Entry, PastCard } from "@/components/AnswerCard";
import { DrawerDigest } from "@/components/DrawerDigest";
import { Fiche } from "@/components/Fiche";
import { askStream } from "@/lib/api";
import { tintVar } from "@/lib/modules";
import { useDrawer, useLibrary } from "@/lib/useLibrary";

const HISTORY_KEY = "sb.history.v1";

function loadHistory(): Entry[] {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function AskDesk() {
  const drawer = useDrawer();
  const { docs } = useLibrary();
  const [question, setQuestion] = useState("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  // History lives in localStorage, which only exists after hydration; reading it in render would mismatch SSR.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setEntries(loadHistory()), []);
  useEffect(() => {
    try {
      const settled = entries.filter((e) => e.status === "done" || e.status === "error").slice(0, 40);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(settled));
    } catch {
      /* history is a convenience */
    }
  }, [entries]);

  const inDrawer = entries.filter((e) => drawer === null || e.course === drawer);
  const active = inDrawer.find((e) => e.id === activeId) ?? inDrawer[0] ?? null;
  const past = inDrawer.filter((e) => e !== active);
  const busy = entries.some((e) => e.status === "searching" || e.status === "writing");

  const update = (id: string, patch: (e: Entry) => Partial<Entry>) =>
    setEntries((all) => all.map((e) => (e.id === id ? { ...e, ...patch(e) } : e)));

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
          endedAt: Date.now(),
        })),
      onError: (msg) => update(id, () => ({ status: "error", error: msg, endedAt: Date.now() })),
    });
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
          <AnswerCard entry={active} activeCite={activeCite} onActiveCite={setActiveCite} onPull={pull} />
        ) : (
          <DrawerDigest docs={docs} drawer={drawer} />
        )}

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
              />
            ))}
          </section>
        )}
      </div>

      <aside className="fiches" aria-label="Cited fiches">
        {active && active.citations.length > 0 ? (
          active.citations.map((c) => (
            <Fiche key={c.n} c={c} active={activeCite === c.n} onActive={setActiveCite} />
          ))
        ) : (
          <p className="fiches-empty">
            {active?.status === "searching" || active?.status === "writing"
              ? "The fiches this answer cites will be pulled here."
              : "Cited fiches are pulled here, each with its call number and page."}
          </p>
        )}
      </aside>
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
