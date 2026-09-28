"use client";

import Link from "next/link";
import { kindOf, readerUrl, type DocumentRow } from "@/lib/api";
import { tintVar } from "@/lib/modules";
import { isNew } from "@/lib/seen";
import { drawerHref } from "@/lib/useLibrary";

/** Empty Ask state: what's in the open drawer, newest first, so the first question has somewhere to start. */
export function DrawerDigest({ docs, drawer }: { docs: DocumentRow[] | null; drawer: string | null }) {
  if (!docs) return null;
  const inDrawer = docs.filter((d) => d.status === "ok" && (drawer === null || d.course === drawer));
  if (inDrawer.length === 0) {
    return (
      <section className="digest">
        <h2>Nothing filed in this drawer yet</h2>
        <p>
          Run the Blackboard sync to fill it: <code>uv run python -m app.sync.blackboard --headless</code> in{" "}
          <code>backend/</code>. Files you drop into <code>inbox/{drawer ?? "<module>"}/</code> are filed too.
        </p>
      </section>
    );
  }
  const fresh = inDrawer.filter(isNew);
  const recent = [...inDrawer].sort((a, b) => b.first_seen.localeCompare(a.first_seen));
  const list = (fresh.length ? fresh : recent).slice(0, 8);

  return (
    <section className="digest">
      <h2>
        {fresh.length ? `${fresh.length} new since your last visit` : "Recently filed"}
        <span>
          {" "}
          · {inDrawer.length} fiche{inDrawer.length > 1 ? "s" : ""} in {drawer ?? "all drawers"}
        </span>
      </h2>
      <ul>
        {list.map((d) => (
          <li key={d.id} style={{ "--tint": tintVar(d.course) } as React.CSSProperties}>
            <Link href={readerUrl(d.id)} dir="auto">
              {d.title}
            </Link>
            <span className="kind">
              {kindOf(d.mime)}
              {drawer === null && d.course ? ` · ${d.course}` : ""}
            </span>
          </li>
        ))}
      </ul>
      <Link className="text-link" href={drawerHref("/documents", drawer)}>
        Open the drawer
      </Link>
    </section>
  );
}
