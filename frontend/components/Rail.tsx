"use client";

import { Archive, History, PenLine } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getJSON, type Health } from "@/lib/api";
import { isKnownModule, modulesOf, OTHER_UNIT, tintVar, UNITS } from "@/lib/modules";
import { ago, isNew, newestFiled } from "@/lib/seen";
import { drawerHref, useDrawer, useLibrary } from "@/lib/useLibrary";

/** The steel card cabinet: views, then one drawer per module, grouped by teaching unit. */
export function Rail() {
  const pathname = usePathname();
  const router = useRouter();
  const drawer = useDrawer();
  const { docs } = useLibrary();
  const [health, setHealth] = useState<Health | "down" | null>(null);

  useEffect(() => {
    getJSON<Health>("/health").then(setHealth).catch(() => setHealth("down"));
  }, []);

  const base = pathname.startsWith("/documents") ? "/documents" : pathname.startsWith("/history") ? "/history" : "/";
  const counts = new Map<string, { n: number; fresh: number }>();
  for (const d of docs ?? []) {
    const k = d.course ?? "";
    const c = counts.get(k) ?? { n: 0, fresh: 0 };
    c.n += 1;
    if (isNew(d)) c.fresh += 1;
    counts.set(k, c);
  }
  const others = [...counts.keys()].filter((c) => c && !isKnownModule(c)).sort();
  const groups = [
    ...UNITS.map((u) => ({ unit: u, modules: modulesOf(u.id) })),
    ...(others.length ? [{ unit: OTHER_UNIT, modules: others }] : []),
  ];

  return (
    <nav className="rail" aria-label="Drawers">
      <Link href={drawerHref("/", drawer)} className="brand">
        Second Brain
      </Link>

      <div className="views">
        <Link href={drawerHref("/", drawer)} aria-current={pathname === "/" ? "page" : undefined}>
          <PenLine size={16} aria-hidden /> Ask
        </Link>
        <Link href={drawerHref("/documents", drawer)} aria-current={base === "/documents" ? "page" : undefined}>
          <Archive size={16} aria-hidden /> Drawer
        </Link>
        <Link href={drawerHref("/history", drawer)} aria-current={base === "/history" ? "page" : undefined}>
          <History size={16} aria-hidden /> History
        </Link>
      </div>

      <label className="drawer-select">
        <span className="sr-only">Drawer</span>
        <select value={drawer ?? ""} onChange={(e) => router.push(drawerHref(base, e.target.value || null))}>
          <option value="">All drawers</option>
          {groups.map(({ unit, modules }) => (
            <optgroup key={unit.id} label={unit.name}>
              {modules.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>

      <div className="cabinet">
        <Link href={base} className="drawer all" aria-current={drawer === null ? "true" : undefined}>
          <span className="label-holder">All drawers</span>
          <span className="count">{docs ? docs.length : ""}</span>
        </Link>
        {groups.map(({ unit, modules }) => (
          <section key={unit.id} className="unit">
            <h2>{unit.name}</h2>
            {modules.map((m) => {
              const c = counts.get(m);
              return (
                <Link
                  key={m}
                  href={drawerHref(base, m)}
                  className={`drawer${c ? "" : " empty"}`}
                  aria-current={drawer === m ? "true" : undefined}
                  style={{ "--tint": tintVar(m) } as React.CSSProperties}
                >
                  <span className="label-holder">{m}</span>
                  {c?.fresh ? <span className="fresh">{c.fresh} new</span> : null}
                  <span className="count">{c ? c.n : "–"}</span>
                </Link>
              );
            })}
          </section>
        ))}
      </div>

      <footer className="health" role="status">
        <Link href="/admin" className="health-link" aria-current={pathname.startsWith("/admin") ? "page" : undefined}>
          <HealthLine health={health} />
        </Link>
        {health && health !== "down" && health.blackboard_login_needed && (
          <Link href="/admin#sync" className="bb-login">
            Blackboard: log in needed
          </Link>
        )}
        {docs && docs.length > 0 && <span className="filed">Last fiche filed {ago(newestFiled(docs))}</span>}
      </footer>
    </nav>
  );
}

function HealthLine({ health }: { health: Health | "down" | null }) {
  if (health === null) return <span>Checking the backend…</span>;
  if (health === "down") return <span className="bad">Backend offline. Start it with uvicorn.</span>;
  if (!health.db.ok) return <span className="bad">Database offline. Run docker compose up.</span>;
  if (!health.ollama.reachable) return <span className="bad">Ollama isn&apos;t running.</span>;
  if (!health.ollama.llm_pulled || !health.ollama.embed_pulled)
    return <span className="bad">A model isn&apos;t pulled yet. See /health.</span>;
  return <span className="ok">Ready · {health.ollama.llm_model}</span>;
}
