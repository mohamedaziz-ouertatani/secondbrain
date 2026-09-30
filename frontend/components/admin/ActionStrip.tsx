"use client";

import Link from "next/link";
import { useState } from "react";
import { useAdminData } from "@/components/admin/AdminData";
import { Explain } from "@/components/admin/Explain";
import { type EnrichmentStatus, postJSON } from "@/lib/api";
import { actionHelp, type Help } from "@/lib/adminHelp";
import { countsLine } from "@/lib/readings";

type Note = { text: string; bad?: boolean } | null;

/** One everyday action: a button, what it does, and its result. */
function Action(props: {
  label: string;
  busyLabel: string;
  help: Help;
  disabled?: boolean;
  run: () => Promise<string>;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note>(null);
  async function go() {
    setBusy(true);
    setNote(null);
    try {
      setNote({ text: await props.run() });
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="action">
      <button type="button" className="quiet-btn" onClick={go} disabled={busy || props.disabled}>
        {busy ? props.busyLabel : props.label}
      </button>
      <Explain line={props.help.line} more={props.help.more} />
      {note && (
        <p className={`action-note${note.bad ? " bad" : ""}`} aria-live="polite">
          {note.text}
        </p>
      )}
    </div>
  );
}

/** Sync, back up, rescan and pause summaries: the things done most days, in one place. */
export function ActionStrip() {
  const { status, sync, refresh } = useAdminData();
  const syncing = sync.value?.job?.state === "running";
  const enrich = status.value?.enrichment ?? null;
  const after = async (text: string) => {
    refresh();
    return text;
  };

  return (
    <section className="admin-card" id="actions" aria-labelledby="actions-h">
      <h2 id="actions-h">Everyday actions</h2>
      <div className="action-strip">
        <Action
          label={syncing ? "Syncing…" : "Sync now"}
          busyLabel="Starting…"
          help={actionHelp.sync}
          disabled={syncing || sync.value === null}
          run={async () => {
            await postJSON("/admin/sync", { mode: "sync" });
            return after("Sync started.");
          }}
        />
        <Action
          label="Back up now"
          busyLabel="Backing up…"
          help={actionHelp.backup}
          run={async () => {
            const r = await postJSON<{ rows: Record<string, number> }>("/admin/backup", {});
            return after(`Backed up ${r.rows.query_log} questions and ${r.rows.planner_items ?? 0} planner items.`);
          }}
        />
        <Action
          label="Rescan inbox"
          busyLabel="Rescanning…"
          help={actionHelp.rescan}
          run={async () => after(`Rescanned: ${countsLine(await postJSON<Record<string, number>>("/ingest/rescan", {}))}.`)}
        />
        {enrich?.enabled && (
          <Action
            label={enrich.paused ? "Resume summaries" : "Pause summaries"}
            busyLabel={enrich.paused ? "Resuming…" : "Pausing…"}
            help={actionHelp.enrich}
            run={async () => {
              const e = await postJSON<EnrichmentStatus>(`/admin/enrich/${enrich.paused ? "resume" : "pause"}`, {});
              return after(e.paused ? "Summaries paused." : "Summaries resumed.");
            }}
          />
        )}
      </div>
      {syncing && (
        <p className="muted">
          A sync is running. <Link href="/admin/library#sync">See its progress</Link>
        </p>
      )}
    </section>
  );
}
