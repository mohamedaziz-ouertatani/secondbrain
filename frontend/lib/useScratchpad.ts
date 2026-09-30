"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { sendJSON } from "./api";
import { createItem, fileNote, listItems, type PlannerItem } from "./planner";
import { appendClip, pickScratch, scratchTitle } from "./scratchpad.ts";

export type SaveState = "loading" | "idle" | "unsaved" | "saving" | "saved" | "error";

const SAVE_AFTER_MS = 800;
const key = (course: string | null) => course ?? "";

/**
 * The drawer's scratchpad note: loaded when the drawer changes, created on the first word typed or
 * clipped, saved shortly after each change. Saves run one at a time so a slow create is never
 * doubled; switching drawers saves what was pending first.
 */
export function useScratchpad(course: string | null) {
  const [body, setBodyState] = useState("");
  const [item, setItem] = useState<PlannerItem | null>(null);
  const [state, setState] = useState<SaveState>("loading");
  const [filed, setFiled] = useState<PlannerItem | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  /** what the current drawer holds right now; saves read it, renders read the state above */
  const live = useRef({ course, body: "", dirty: false, ready: false });
  /** scratchpad notes known per drawer, so a queued save patches the note an earlier save created */
  const known = useRef(new Map<string, PlannerItem>());
  const queue = useRef<Promise<void>>(Promise.resolve());
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const save = useCallback((): Promise<void> => {
    clearTimeout(timer.current);
    const s = live.current;
    if (!s.dirty || !s.ready) return queue.current;
    s.dirty = false;
    const { course: c, body: text } = s;
    const current = () => live.current.course === c;
    setState("saving");
    queue.current = queue.current.then(async () => {
      const had = known.current.get(key(c));
      if (!had && !text.trim()) {
        if (current()) setState("idle");
        return;
      }
      try {
        // patched without announcing: the note isn't dated, so no Coming-up strip needs a reload per keystroke
        const saved = had
          ? await sendJSON<PlannerItem>("PATCH", `/planner/items/${had.id}`, { body: text })
          : await createItem({ kind: "note", title: scratchTitle(c), body: text, course: c });
        known.current.set(key(c), saved);
        if (current()) {
          setItem(saved);
          setState(live.current.dirty ? "unsaved" : "saved");
        }
      } catch {
        if (current()) {
          live.current.dirty = true;
          setState("error");
        }
      }
    });
    return queue.current;
  }, []);

  const setBody = useCallback(
    (text: string) => {
      live.current.body = text;
      live.current.dirty = true;
      setBodyState(text);
      setState("unsaved");
      setFiled(null);
      clearTimeout(timer.current);
      timer.current = setTimeout(save, SAVE_AFTER_MS);
    },
    [save],
  );

  const append = useCallback((clip: string) => setBody(appendClip(live.current.body, clip)), [setBody]);

  // a new drawer shows its own scratchpad: clear the old one's view while it loads
  const [shownFor, setShownFor] = useState(course);
  if (shownFor !== course) {
    setShownFor(course);
    setBodyState("");
    setItem(null);
    setFiled(null);
    setFileError(null);
    setState("loading");
  }

  useEffect(() => {
    live.current = { course, body: "", dirty: false, ready: false };
    const ctl = new AbortController();
    listItems({ course, kind: "note" }, ctl.signal)
      .then((items) => {
        const found = pickScratch(items, course);
        if (found) known.current.set(key(course), found);
        else known.current.delete(key(course));
        const s = live.current;
        // anything clipped while this loaded goes after what was already there
        s.body = s.dirty && found ? appendClip(found.body, s.body.trim()) : s.dirty ? s.body : (found?.body ?? "");
        s.ready = true;
        setBodyState(s.body);
        setItem(found);
        setState(s.dirty ? "unsaved" : "idle");
        if (s.dirty) save();
      })
      .catch((e) => {
        if (e?.name !== "AbortError") setState("error");
      });
    return () => {
      ctl.abort();
      save();
    };
  }, [course, save]);

  /** Files the scratchpad into its drawer as a .md; the next clip starts a fresh one. */
  const file = useCallback(async () => {
    setFileError(null);
    await save();
    const c = live.current.course;
    const note = known.current.get(key(c));
    if (!note || live.current.dirty) return;
    try {
      const done = await fileNote(note.id);
      known.current.delete(key(c));
      if (live.current.course !== c) return;
      live.current.body = "";
      setBodyState("");
      setItem(null);
      setFiled(done);
      setState("idle");
    } catch (e) {
      setFileError(e instanceof Error ? e.message : "Couldn't file the scratchpad.");
    }
  }, [save]);

  return { body, setBody, append, item, state, file, filed, fileError };
}
