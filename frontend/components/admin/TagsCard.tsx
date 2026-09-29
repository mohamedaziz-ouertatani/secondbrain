"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, getJSON, postJSON, sendJSON, type TagRow } from "@/lib/api";

type Note = { text: string; bad?: boolean } | null;

/** Per-module tag vocabulary: rename, merge two, delete, or run the merge pass now. */
export function TagsCard() {
  const [courses, setCourses] = useState<string[]>([]);
  const [course, setCourse] = useState("");
  const [tags, setTags] = useState<TagRow[] | null>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null);
  const [note, setNote] = useState<Note>(null);

  useEffect(() => {
    getJSON<string[]>("/courses")
      .then((c) => {
        setCourses(c);
        setCourse((prev) => prev || c[0] || "");
      })
      .catch(() => setNote({ text: "Couldn't load the modules.", bad: true }));
  }, []);

  const load = useCallback(() => {
    if (!course) return;
    getJSON<TagRow[]>(`/tags?course=${encodeURIComponent(course)}`)
      .then((t) => {
        setTags(t);
        setPicked([]);
      })
      .catch(() => setNote({ text: "Couldn't load the tags.", bad: true }));
  }, [course]);
  useEffect(load, [load]);

  async function act(run: () => Promise<string>) {
    setNote(null);
    try {
      setNote({ text: await run() });
    } catch (e) {
      setNote({ text: e instanceof ApiError ? e.message : "That didn't work.", bad: true });
    }
    load();
  }

  function mergePicked() {
    const [a, b] = picked.map((id) => tags!.find((t) => t.id === id)!);
    const [from, into] = a.count > b.count ? [b, a] : [a, b];
    act(async () => {
      await postJSON("/admin/tags/merge", { from_id: from.id, into: into.id });
      return `Merged “${from.name}” into “${into.name}”.`;
    });
  }

  function runPass() {
    act(async () => {
      const r = await postJSON<{ new_raw: number; new_tags: number; removed: number }>("/admin/tags/vocab", { course });
      return `${r.new_raw} new raw tags, ${r.new_tags} new tags, ${r.removed} unused removed.`;
    });
  }

  function rename(id: number, name: string) {
    setEditing(null);
    act(async () => {
      const t = await sendJSON<TagRow>("PATCH", `/admin/tags/${id}`, { name });
      return `Renamed to “${t.name}”.`;
    });
  }

  function remove(t: TagRow) {
    act(async () => {
      await sendJSON("DELETE", `/admin/tags/${t.id}`, {});
      return `Deleted “${t.name}”. It won't come back on later passes.`;
    });
  }

  return (
    <section className="admin-card" aria-labelledby="tags-h">
      <header className="admin-card-head">
        <h2 id="tags-h">Tags</h2>
        <span className="admin-actions">
          <select value={course} onChange={(e) => setCourse(e.target.value)} aria-label="Module">
            {courses.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <button type="button" className="quiet-btn" disabled={picked.length !== 2} onClick={mergePicked}>
            Merge the two selected
          </button>
          <button type="button" className="quiet-btn" disabled={!course} onClick={runPass}>
            Run vocabulary pass
          </button>
        </span>
      </header>
      {note && <p className={`action-note${note.bad ? " bad" : ""}`}>{note.text}</p>}
      {!tags ? (
        <p className="muted">Loading tags…</p>
      ) : tags.length === 0 ? (
        <p className="muted">No tags yet. They appear once this module&apos;s files are summarised.</p>
      ) : (
        <div className="tags-scroll">
          <table className="admin-table">
            <thead>
              <tr>
                <th scope="col">
                  <span className="sr-only">Select</span>
                </th>
                <th scope="col">Tag</th>
                <th scope="col">Files</th>
                <th scope="col">Merged forms</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {tags.map((t) => (
                <tr key={t.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select ${t.name}`}
                      checked={picked.includes(t.id)}
                      onChange={(e) =>
                        setPicked(e.target.checked ? [...picked, t.id].slice(-2) : picked.filter((id) => id !== t.id))
                      }
                    />
                  </td>
                  <th scope="row" dir="auto">
                    {editing?.id === t.id ? (
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          rename(t.id, editing.name);
                        }}
                      >
                        <input
                          autoFocus
                          value={editing.name}
                          onChange={(e) => setEditing({ id: t.id, name: e.target.value })}
                          onBlur={() => setEditing(null)}
                          onKeyDown={(e) => e.key === "Escape" && setEditing(null)}
                          aria-label="New name"
                        />
                      </form>
                    ) : (
                      t.name
                    )}
                  </th>
                  <td>{t.count}</td>
                  <td className="muted" dir="auto">
                    {t.raws.join(", ") || "–"}
                  </td>
                  <td>
                    <span className="row-actions">
                      <button type="button" className="quiet-btn" onClick={() => setEditing({ id: t.id, name: t.name })}>
                        Rename
                      </button>
                      <button type="button" className="quiet-btn" onClick={() => remove(t)}>
                        Delete
                      </button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
