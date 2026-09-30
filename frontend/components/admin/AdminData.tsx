"use client";

import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { type AdminLibrary, type AdminStatus, getJSON, type InsightsSummary, type SyncStatus } from "@/lib/api";
import { type AdminTab, type AttentionItem, attention, badgeCounts } from "@/lib/attention";

const POLL_MS = 10_000;

/** One endpoint's reading; `value` keeps the last good reading after a failure. */
export type Slot<T> = { value: T | null; failed: boolean };
export type AdminData = {
  status: Slot<AdminStatus>;
  library: Slot<AdminLibrary>;
  sync: Slot<SyncStatus>;
  insights: Slot<InsightsSummary>;
  items: AttentionItem[];
  badges: Record<AdminTab, number>;
  offline: boolean;
  now: Date;
  refresh: () => void;
};

const EMPTY = { value: null, failed: false };
const input = <T,>(s: Slot<T>) => (s.failed ? ("failed" as const) : s.value);
const Ctx = createContext<AdminData | null>(null);

export function useAdminData(): AdminData {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAdminData is only available inside the admin layout");
  return v;
}

/** Polls what the Overview and the tab badges need, every 10 s while the tab is visible. */
export function AdminDataProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Slot<AdminStatus>>(EMPTY);
  const [library, setLibrary] = useState<Slot<AdminLibrary>>(EMPTY);
  const [sync, setSync] = useState<Slot<SyncStatus>>(EMPTY);
  const [insights, setInsights] = useState<Slot<InsightsSummary>>(EMPTY);
  const [now, setNow] = useState(() => new Date());

  const refresh = useCallback(() => {
    if (document.visibilityState !== "visible") return;
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const pull = <T,>(path: string, set: Dispatch<SetStateAction<Slot<T>>>) =>
      getJSON<T>(path).then(
        (value) => set({ value, failed: false }),
        () => set((prev) => ({ value: prev.value, failed: true })),
      );
    Promise.all([
      pull("/admin/status", setStatus),
      pull("/admin/library", setLibrary),
      pull("/admin/sync", setSync),
      pull(`/admin/insights?days=7&tz=${encodeURIComponent(tz)}`, setInsights),
    ]).then(() => setNow(new Date()));
  }, []);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, POLL_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [refresh]);

  const value = useMemo<AdminData>(() => {
    const items = attention({
      status: input(status),
      library: input(library),
      sync: input(sync),
      insights: input(insights),
      now,
    });
    return {
      status,
      library,
      sync,
      insights,
      items,
      badges: badgeCounts(items),
      offline: status.failed && library.failed && sync.failed && insights.failed,
      now,
      refresh,
    };
  }, [status, library, sync, insights, now, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
