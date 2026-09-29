"use client";

import { Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { UndoNote } from "@/components/UndoNote";
import { Agenda } from "@/components/planner/Agenda";
import { CaptureLine } from "@/components/planner/CaptureLine";
import { ItemRow } from "@/components/planner/ItemRow";
import { MonthGrid } from "@/components/planner/MonthGrid";
import { useUndoDelete } from "@/lib/history";
import { deleteItem, type PlannerItem, plannerHref, useModules, usePlannerItems } from "@/lib/planner";
import { useDrawer } from "@/lib/useLibrary";

const VIEW_KEY = "sb.planner.view";

function storedView(): "agenda" | "month" {
  try {
    return localStorage.getItem(VIEW_KEY) === "month" ? "month" : "agenda";
  } catch {
    return "agenda";
  }
}

function matches(i: PlannerItem, q: string): boolean {
  const s = q.trim().toLowerCase();
  return !s || i.title.toLowerCase().includes(s) || i.body.toLowerCase().includes(s);
}

function PlannerView() {
  const drawer = useDrawer();
  const router = useRouter();
  const modules = useModules();
  const { items, error } = usePlannerItems(drawer);
  const { hidden, remove, undo, pending, failed } = useUndoDelete(deleteItem);
  const openParam = useSearchParams().get("open");
  const [openId, setOpenId] = useState<number | null>(null);
  const [view, setViewState] = useState<"agenda" | "month">(storedView);
  const [month, setMonth] = useState(() => new Date());
  const [focusDay, setFocusDay] = useState<string | null>(null);
  const [tab, setTab] = useState<"todo" | "note">("todo");
  const [q, setQ] = useState("");

  const setView = (v: "agenda" | "month") => {
    setViewState(v);
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* storage may be blocked */
    }
  };
  const activeId = openId ?? (openParam ? Number(openParam) : null);
  const openItem = (i: PlannerItem) => setOpenId(i.id);
  const close = () => {
    setOpenId(null);
    if (openParam) router.replace(plannerHref(null, drawer));
  };

  const live = (items ?? []).filter((i) => !hidden.has(i.id));
  const open = live.find((i) => i.id === activeId) ?? null;
  const todos = live
    .filter((i) => i.kind === "todo" && matches(i, q))
    .sort((a, b) => Number(!!a.done_at) - Number(!!b.done_at));
  const openTodos = todos.filter((i) => !i.done_at);
  const doneTodos = todos.filter((i) => i.done_at);
  const notes = live
    .filter((i) => i.kind === "note" && matches(i, q))
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <div className="drawer-view planner-view">
      <header className="drawer-head">
        <div>
          <h1>Planner</h1>
          <p>{drawer ? `Notes, to-dos and dates in ${drawer}` : "Notes, to-dos and dates across every drawer"}</p>
        </div>
      </header>

      <section className="card plan-card capture-card" aria-label="Capture">
        <CaptureLine drawer={drawer} modules={modules} onSaved={() => {}} />
      </section>

      {error && <p className="notice bad">Couldn&apos;t load the planner. Is the backend running?</p>}
      {items === null && !error && <p className="muted">Opening the planner…</p>}

      {items !== null && (
        <div className="planner-grid">
          <section className="card plan-card" aria-labelledby="cal-h">
            <header className="plan-card-head">
              <h2 id="cal-h">Dates</h2>
              <div className="segmented" role="group" aria-label="View">
                <button type="button" aria-pressed={view === "agenda"} onClick={() => setView("agenda")}>
                  Agenda
                </button>
                <button type="button" aria-pressed={view === "month"} onClick={() => setView("month")}>
                  Month
                </button>
              </div>
            </header>
            {view === "agenda" ? (
              <Agenda items={live} onOpen={openItem} focusDay={focusDay} />
            ) : (
              <MonthGrid
                items={live}
                month={month}
                onMonth={setMonth}
                onOpen={openItem}
                onDay={(k) => {
                  setFocusDay(k);
                  setView("agenda");
                }}
              />
            )}
          </section>

          <section className="card plan-card" aria-labelledby="lists-h">
            <header className="plan-card-head">
              <h2 id="lists-h" className="sr-only">
                To-dos and notes
              </h2>
              <div className="segmented" role="group" aria-label="List">
                <button type="button" aria-pressed={tab === "todo"} onClick={() => setTab("todo")}>
                  To-dos {openTodos.length > 0 && `(${openTodos.length})`}
                </button>
                <button type="button" aria-pressed={tab === "note"} onClick={() => setTab("note")}>
                  Notes {notes.length > 0 && `(${notes.length})`}
                </button>
              </div>
              <label className="search">
                <Search size={15} aria-hidden />
                <span className="sr-only">Search the planner</span>
                <input type="search" dir="auto" value={q} placeholder="Search…" onChange={(e) => setQ(e.target.value)} />
              </label>
            </header>
            {tab === "todo" ? (
              <>
                {openTodos.length === 0 && <p className="muted plan-empty">{q ? `No to-dos match “${q}”.` : "No open to-dos."}</p>}
                <ul className="plan-list">
                  {openTodos.map((i) => (
                    <ItemRow key={i.id} item={i} onOpen={openItem} />
                  ))}
                </ul>
                {doneTodos.length > 0 && (
                  <details className="plan-done">
                    <summary>Done ({doneTodos.length})</summary>
                    <ul className="plan-list">
                      {doneTodos.map((i) => (
                        <ItemRow key={i.id} item={i} onOpen={openItem} />
                      ))}
                    </ul>
                  </details>
                )}
              </>
            ) : (
              <>
                {notes.length === 0 && (
                  <p className="muted plan-empty">
                    {q ? `No notes match “${q}”.` : "No notes yet. Anything you type without a date becomes one."}
                  </p>
                )}
                <ul className="plan-list">
                  {notes.map((i) => (
                    <ItemRow key={i.id} item={i} onOpen={openItem} />
                  ))}
                </ul>
              </>
            )}
          </section>
        </div>
      )}

      {/* Task 8: the item panel for `open` goes here */}

      <UndoNote pending={pending} failed={failed} onUndo={undo} what="item" />
    </div>
  );
}

export default function PlannerPage() {
  return (
    <Suspense>
      <PlannerView />
    </Suspense>
  );
}
