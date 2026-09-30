"use client";

import { useAdminData } from "@/components/admin/AdminData";
import { age, gpuShareReading, indexReading, isBackupOld, isSyncOld, servicesReading } from "@/lib/readings";

type Tile = { label: string; value: string; reading: string | null; bad?: boolean };

/** Five readings, each with what it means. */
export function GlanceTiles() {
  const { status, sync, now } = useAdminData();
  const s = status.value;
  const y = sync.value;
  if (!s) return null;

  const svc = servicesReading(s.services);
  const llm = s.llm;
  const tiles: Tile[] = [
    { label: "Services", value: svc.ok ? "Ready" : "Down", reading: svc.text, bad: !svc.ok },
    {
      label: "Answer model",
      value: llm?.model ?? "Unknown",
      reading: !llm
        ? "Ollama isn't answering"
        : llm.loaded
          ? gpuShareReading(llm.gpu_share)
          : "not loaded: the next question loads it (about 10 s)",
    },
    { label: "Index", value: s.index ? `${s.index.documents.toLocaleString("en-GB")} files` : "–", reading: indexReading(s.index) },
    {
      label: "Last sync",
      value: y?.last_full_sync ? age(y.last_full_sync, now) : y ? "Never" : "–",
      reading: !y
        ? null
        : y.auto_days === 0
          ? "automatic sync off"
          : isSyncOld(y.last_full_sync, y.auto_days, now)
            ? "overdue"
            : `automatic every ${y.auto_days} days`,
      bad: !!y && y.auto_days > 0 && isSyncOld(y.last_full_sync, y.auto_days, now),
    },
    {
      label: "Last backup",
      value: s.backup ? age(s.backup.at, now) : "None",
      reading: isBackupOld(s.backup?.at ?? null, now) ? "older than 2 days" : `${s.backup!.kept} kept`,
      bad: isBackupOld(s.backup?.at ?? null, now),
    },
  ];

  return (
    <section className="glance" aria-label="At a glance">
      {tiles.map((t) => (
        <div key={t.label} className={`glance-cell${t.bad ? " bad" : ""}`}>
          <span className="glance-label">{t.label}</span>
          <span className="glance-value">{t.value}</span>
          {t.reading && <span className="glance-reading">{t.reading}</span>}
        </div>
      ))}
    </section>
  );
}
