"use client";

import { useCallback, useEffect, useState } from "react";
import { API_URL, getJSON, sendJSON } from "./api";
import { moduleCode } from "./modules";
import { dayKey, daysOf } from "./planDays";

export type Kind = "note" | "todo" | "event";

export type PlannerItem = {
  id: number;
  kind: Kind;
  title: string;
  body: string;
  course: string | null;
  /** an event's start or a to-do's due time */
  starts_at: string | null;
  ends_at: string | null;
  all_day: boolean;
  done_at: string | null;
  source: "me" | "blackboard";
  source_id: string | null;
  /** Blackboard no longer lists it; kept, struck through */
  removed_at: string | null;
  /** inbox-relative .md once a note is filed into its drawer */
  filed_path: string | null;
  created_at: string;
  updated_at: string;
};

export type Span = { start: number; end: number; role: "course" | "kind" | "date" | "time" };

/** What /planner/parse read in a typed line; nothing is saved yet. */
export type Draft = {
  kind: Kind;
  title: string;
  course: string | null;
  starts_at: string | null;
  ends_at: string | null;
  all_day: boolean;
  matched: Span[];
};

export type ItemFields = Partial<Pick<PlannerItem, "kind" | "title" | "body" | "course" | "starts_at" | "ends_at" | "all_day">> & {
  done?: boolean;
};

export const KIND_LABEL: Record<Kind, string> = { note: "Note", todo: "To-do", event: "Event" };

/** Fired after any planner change, so lists, Coming-up strips and the rail badge reload. */
export const PLANNER_CHANGED = "sb:planner";
export function announce() {
  window.dispatchEvent(new Event(PLANNER_CHANGED));
}

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

export function listItems(opts: { course?: string | null; kind?: Kind }, signal?: AbortSignal): Promise<PlannerItem[]> {
  const p = new URLSearchParams();
  if (opts.course) p.set("course", opts.course);
  if (opts.kind) p.set("kind", opts.kind);
  return getJSON<PlannerItem[]>(`/planner/items?${p}`, signal);
}

export function fetchUpcoming(course: string | null, days = 7, signal?: AbortSignal): Promise<PlannerItem[]> {
  const p = new URLSearchParams({ days: String(days) });
  if (course) p.set("course", course);
  return getJSON<PlannerItem[]>(`/planner/upcoming?${p}`, signal);
}

export function fetchModules(): Promise<string[]> {
  return getJSON<string[]>("/courses");
}

export async function createItem(f: ItemFields & { kind: Kind }): Promise<PlannerItem> {
  const item = await sendJSON<PlannerItem>("POST", "/planner/items", f);
  announce();
  return item;
}

export async function patchItem(id: number, f: ItemFields): Promise<PlannerItem> {
  const item = await sendJSON<PlannerItem>("PATCH", `/planner/items/${id}`, f);
  announce();
  return item;
}

export async function fileNote(id: number): Promise<PlannerItem> {
  const item = await sendJSON<PlannerItem>("POST", `/planner/items/${id}/file`, {});
  announce();
  return item;
}

/** Used by useUndoDelete: true if the item is gone (a 404 counts). */
export async function deleteItem(id: number): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/planner/items/${id}`, { method: "DELETE", keepalive: true });
    if (res.ok) announce();
    return res.ok || res.status === 404;
  } catch {
    return false;
  }
}

export async function parseLine(text: string, course: string | null, signal?: AbortSignal): Promise<Draft> {
  const res = await fetch(`${API_URL}/planner/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, course, tz: TZ }),
    signal,
  });
  if (!res.ok) throw new Error(`/planner/parse returned ${res.status}`);
  return res.json();
}

// ---- dates: stored UTC, shown local ------------------------------------------

const pad = (n: number) => String(n).padStart(2, "0");

export { dayKey, daysOf };

export function isOverdue(i: PlannerItem, now = new Date()): boolean {
  return i.kind === "todo" && !i.done_at && !i.removed_at && !!i.starts_at && new Date(i.starts_at) < now;
}

const hm = (d: Date) => d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const dayShort = (d: Date) => d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });

/** "due Fri 2 Oct 23:59", "Mon 5 Oct 14:30–16:00", "Sat 3 Oct", "Mon 14 Dec – Sat 26 Dec"; "" when undated. */
export function whenLabel(i: Pick<PlannerItem, "kind" | "starts_at" | "ends_at" | "all_day">): string {
  if (!i.starts_at) return "";
  const d = new Date(i.starts_at);
  if (i.all_day) {
    const days = daysOf(i);
    if (days.length < 2) return dayShort(d);
    const [y, m, day] = days[days.length - 1].split("-").map(Number);
    return `${dayShort(d)} – ${dayShort(new Date(y, m - 1, day))}`;
  }
  const t = i.ends_at ? `${hm(d)}–${hm(new Date(i.ends_at))}` : hm(d);
  return `${i.kind === "todo" ? "due " : ""}${dayShort(d)} ${t}`;
}

/** "Today", "Tomorrow", else "Friday 2 Oct", for a dayKey. */
export function dayHeading(key: string, now = new Date()): string {
  const [y, m, d] = key.split("-").map(Number);
  const day = new Date(y, m - 1, d);
  const diff = Math.round((day.getTime() - new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  return day.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" });
}

/** The parser's reading as a call number: "TO-DO · DEVOPS · due Fri 2 Oct 23:59". */
export function readingLabel(d: Draft): string {
  return [KIND_LABEL[d.kind].toUpperCase(), d.course ? moduleCode(d.course) : null, whenLabel(d)]
    .filter(Boolean)
    .join(" · ");
}

/** ISO -> the value of an <input type="datetime-local">. */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  return `${dayKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** ISO -> the value of an <input type="date">. */
export function toLocalDate(iso: string): string {
  return dayKey(new Date(iso));
}

/** A date or datetime-local input value -> ISO. A bare date is local midnight, not UTC. */
export function fromLocalInput(v: string): string {
  return new Date(v.length === 10 ? `${v}T00:00` : v).toISOString();
}

export function plannerHref(id: number | null, drawer: string | null): string {
  const p = new URLSearchParams();
  if (drawer) p.set("m", drawer);
  if (id !== null) p.set("open", String(id));
  const s = p.toString();
  return s ? `/planner?${s}` : "/planner";
}

// ---- hooks ------------------------------------------------------------------------

function useReloading<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState(false);
  const reload = useCallback(() => {
    const ctl = new AbortController();
    load(ctl.signal)
      .then((d) => {
        setData(d);
        setError(false);
      })
      .catch((e) => {
        if (e?.name !== "AbortError") setError(true);
      });
    return ctl;
  }, [load]);
  useEffect(() => {
    let ctl = reload();
    const again = () => {
      ctl.abort();
      ctl = reload();
    };
    window.addEventListener(PLANNER_CHANGED, again);
    return () => {
      ctl.abort();
      window.removeEventListener(PLANNER_CHANGED, again);
    };
  }, [reload]);
  return { data, error };
}

/** Every item in a drawer (or all), reloaded after any planner change. */
export function usePlannerItems(course: string | null) {
  const load = useCallback((s: AbortSignal) => listItems({ course }, s), [course]);
  const { data, error } = useReloading(load);
  return { items: data, error };
}

export function useUpcoming(course: string | null, days = 7) {
  const load = useCallback((s: AbortSignal) => fetchUpcoming(course, days, s), [course, days]);
  return useReloading(load).data;
}

/** Module names for pickers: the library's courses. */
export function useModules(): string[] {
  const [mods, setMods] = useState<string[]>([]);
  useEffect(() => {
    fetchModules().then(setMods).catch(() => setMods([]));
  }, []);
  return mods;
}
