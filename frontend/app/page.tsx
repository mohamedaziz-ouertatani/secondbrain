"use client";

import { useEffect, useRef, useState } from "react";
import { Answer, type Entry } from "@/components/Answer";
import { askStream, getJSON } from "@/lib/api";

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [course, setCourse] = useState("");
  const [courses, setCourses] = useState<string[]>([]);
  const [entries, setEntries] = useState<Entry[]>([]);
  const busy = entries[0]?.status === "streaming";
  const nextId = useRef(1);

  useEffect(() => {
    getJSON<string[]>("/courses").then(setCourses).catch(() => setCourses([]));
  }, []);

  const update = (id: number, patch: (e: Entry) => Partial<Entry>) =>
    setEntries((all) => all.map((e) => (e.id === id ? { ...e, ...patch(e) } : e)));

  async function submit() {
    const q = question.trim();
    if (!q || busy) return;
    const id = nextId.current++;
    const scope = course || null;
    setEntries((all) => [
      { id, question: q, course: scope, text: "", status: "streaming", citations: [], valid: null },
      ...all,
    ]);
    setQuestion("");
    await askStream(q, scope, {
      onToken: (t) => update(id, (e) => ({ text: e.text + t })),
      onDone: (d) =>
        update(id, () => ({ text: d.answer, citations: d.citations, valid: d.citation_valid, status: "done" })),
      onError: (msg) => update(id, () => ({ status: "error", error: msg })),
    });
  }

  return (
    <>
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label htmlFor="q" className="sr-only">Your question</label>
        <textarea
          id="q"
          dir="auto"
          rows={2}
          value={question}
          placeholder="Ask anything from your courses and notes…"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          autoFocus
        />
        <div className="ask-row">
          <label className="course-pick">
            <span>Search in</span>
            <select value={course} onChange={(e) => setCourse(e.target.value)}>
              <option value="">all courses</option>
              {courses.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={busy || !question.trim()}>
            {busy ? "Answering…" : "Ask"}
          </button>
        </div>
      </form>

      {entries.length === 0 ? (
        <section className="empty">
          <p>Answers come only from your own files, and every claim links to the page it came from.</p>
          <p>
            To add material, drop PDFs, Markdown or text files into <code>inbox/&lt;course&gt;/</code>. They show up
            in your library within a few seconds.
          </p>
        </section>
      ) : (
        entries.map((e) => <Answer key={e.id} entry={e} />)
      )}
    </>
  );
}
