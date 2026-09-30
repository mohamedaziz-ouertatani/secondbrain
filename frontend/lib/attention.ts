/**
 * What needs the student on the admin Overview, and the tab badges. Worked out in the browser from
 * four existing endpoints; pure (tested with node's runner). `null` input: still loading.
 */
import type { AdminLibrary, AdminStatus, InsightsSummary, SyncStatus } from "./api.ts";
import { daysSince, isBackupOld, isSyncOld, percent, servicesReading } from "./readings.ts";

export type Severity = "bad" | "warn" | "info";
export type AdminTab = "overview" | "library" | "quality" | "settings";
export type AttentionItem = { id: string; severity: Severity; text: string; tab: AdminTab; href: string };
export type Input<T> = T | null | "failed";
export type AttentionInputs = {
  status: Input<AdminStatus>;
  library: Input<AdminLibrary>;
  sync: Input<SyncStatus>;
  insights: Input<InsightsSummary>;
  now: Date;
};

export const INVALID_MAX = 0.1;
export const REFUSED_MAX = 0.25;
export const MIN_QUESTIONS = 10;

type Source = "status" | "library" | "sync" | "insights";
const WHERE: Record<Source, { tab: AdminTab; href: string; what: string }> = {
  status: { tab: "overview", href: "/admin#details", what: "the services" },
  library: { tab: "library", href: "/admin/library#library", what: "the library" },
  sync: { tab: "library", href: "/admin/library#sync", what: "the Blackboard sync" },
  insights: { tab: "quality", href: "/admin/quality#insights", what: "recent answers" },
};
const RANK: Record<Severity, number> = { bad: 0, warn: 1, info: 2 };
const files = (n: number) => `${n} file${n === 1 ? "" : "s"}`;

export function attention(i: AttentionInputs): AttentionItem[] {
  const out: AttentionItem[] = [];
  const add = (id: string, severity: Severity, text: string, from: Source, href = WHERE[from].href) =>
    out.push({ id, severity, text, tab: WHERE[from].tab, href });

  for (const from of ["status", "library", "sync", "insights"] as const)
    if (i[from] === "failed") add(`failed:${from}`, "warn", `Couldn't check ${WHERE[from].what}.`, from);

  const { status, library, sync, insights, now } = i;

  if (status && status !== "failed") {
    const svc = servicesReading(status.services);
    if (!svc.ok) add("services", "bad", svc.text, "status");
    const at = status.backup?.at ?? null;
    if (isBackupOld(at, now))
      add(
        "backup",
        "warn",
        at
          ? `The last backup is ${Math.floor(daysSince(at, now))} days old. Back up now so a reset can't lose your history.`
          : "There's no backup yet. The backend makes one a few minutes after it starts, or back up now.",
        "status",
        "/admin#actions",
      );
  }

  if (sync && sync !== "failed") {
    const last = sync.runs.find((r) => r.mode === "sync" && r.state !== "running");
    if (sync.login_needed)
      add("bb-login", "bad", "Blackboard needs you to log in again. Until then, syncs can't fetch new files.", "sync");
    else if (last?.state === "failed" || last?.state === "login_required")
      add(
        "bb-failed",
        "bad",
        last.state === "failed"
          ? `The last Blackboard sync failed${last.error ? `: ${last.error}` : ""}. New course files may be missing.`
          : "The last Blackboard sync stopped at the login page. New course files may be missing.",
        "sync",
      );
    else if (isSyncOld(sync.last_full_sync, sync.auto_days, now))
      add(
        "bb-old",
        "warn",
        sync.last_full_sync
          ? `No full Blackboard sync for ${Math.floor(daysSince(sync.last_full_sync, now))} days, so recent course files may be missing.`
          : "You haven't run a full Blackboard sync from here yet.",
        "sync",
      );
  }

  if (library && library !== "failed") {
    const n = library.problems.length;
    if (n)
      add(
        "unreadable",
        "warn",
        `${files(n)} couldn't be read, so ${n === 1 ? "its" : "their"} pages never appear in answers.`,
        "library",
      );
    const m = library.summary_errors.length;
    if (m)
      add(
        "summaries",
        "info",
        `${files(m)} couldn't be summarised. ${m === 1 ? "It still appears" : "They still appear"} in answers.`,
        "library",
      );
  }

  if (insights && insights !== "failed" && insights.questions >= MIN_QUESTIONS) {
    const q = insights.questions;
    if (insights.invalid / q > INVALID_MAX)
      add(
        "invalid",
        "warn",
        `${percent(insights.invalid, q)}% of answers in the last 7 days had invalid citations (${insights.invalid} of ${q}).`,
        "insights",
      );
    if (insights.refused / q > REFUSED_MAX)
      add(
        "refused",
        "warn",
        `${percent(insights.refused, q)}% of questions in the last 7 days were refused (${insights.refused} of ${q}). Material may be missing, or the refusal threshold is too high.`,
        "insights",
      );
  }

  return out.sort((a, b) => RANK[a.severity] - RANK[b.severity]);
}

/** Problems per tab for the tab bar; info items show in the list but don't count. */
export function badgeCounts(items: AttentionItem[]): Record<AdminTab, number> {
  const c: Record<AdminTab, number> = { overview: 0, library: 0, quality: 0, settings: 0 };
  for (const it of items) if (it.severity !== "info") c[it.tab]++;
  return c;
}
