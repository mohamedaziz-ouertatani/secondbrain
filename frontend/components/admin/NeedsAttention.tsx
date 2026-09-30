"use client";

import Link from "next/link";
import { useAdminData } from "@/components/admin/AdminData";
import type { Severity } from "@/lib/attention";

const SEVERITY: Record<Severity, string> = { bad: "Problem", warn: "Check", info: "Note" };

/** What needs the student, most urgent first; each item links to where it's fixed. */
export function NeedsAttention() {
  const { items, status, library, sync, insights, offline } = useAdminData();
  if (offline) return null; // the layout already says the backend is offline
  const loading = [status, library, sync, insights].some((s) => s.value === null && !s.failed);
  return (
    <section className="admin-card attention" aria-labelledby="attention-h">
      <h2 id="attention-h">Needs attention</h2>
      {items.length > 0 ? (
        <ul className="attention-list">
          {items.map((it) => (
            <li key={it.id} className="attention-item">
              <span className={`stamp ${it.severity}`}>{SEVERITY[it.severity]}</span>
              <Link href={it.href}>{it.text}</Link>
            </li>
          ))}
        </ul>
      ) : loading ? (
        <p className="muted">Checking the cabinet…</p>
      ) : (
        <p className="all-clear">Nothing needs you. Everything is running and up to date.</p>
      )}
    </section>
  );
}
