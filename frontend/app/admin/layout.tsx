"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect } from "react";
import { AdminDataProvider, useAdminData } from "@/components/admin/AdminData";
import { pageIntro } from "@/lib/adminHelp";
import type { AdminTab } from "@/lib/attention";

const TABS: { tab: AdminTab; href: string; label: string }[] = [
  { tab: "overview", href: "/admin", label: "Overview" },
  { tab: "library", href: "/admin/library", label: "Library" },
  { tab: "quality", href: "/admin/quality", label: "Quality" },
  { tab: "settings", href: "/admin/settings", label: "Settings" },
];

const activeTab = (path: string): AdminTab => TABS.slice(1).find((t) => path.startsWith(t.href))?.tab ?? "overview";

const HASH_WAIT_MS = 5000; // how long to wait for the target to appear
const HASH_SETTLE_MS = 1500; // how long to keep it in place while cards above it finish loading

/**
 * Deep links like /admin/library#sync: the cards render their ids only once their data arrives, after
 * the browser has already tried to scroll, and cards above the target can grow after it lands. Wait for
 * the element, scroll to it, and keep it there while the page fills in, until the student scrolls.
 */
function useHashScroll(pathname: string) {
  useEffect(() => {
    const go = () => {
      const id = decodeURIComponent(window.location.hash.slice(1));
      if (!id) return () => {};
      let settleUntil = 0;
      const land = () => {
        const el = document.getElementById(id);
        if (!el) return;
        settleUntil ||= Date.now() + HASH_SETTLE_MS;
        el.scrollIntoView({ block: "start" });
        if (Date.now() > settleUntil) stop();
      };
      const seen = new MutationObserver(land);
      const timer = window.setTimeout(() => stop(), HASH_WAIT_MS);
      const settle = window.setInterval(() => settleUntil && Date.now() > settleUntil && stop(), 250);
      const user = ["wheel", "touchstart", "keydown", "mousedown"];
      const stop = () => {
        seen.disconnect();
        window.clearTimeout(timer);
        window.clearInterval(settle);
        for (const e of user) window.removeEventListener(e, stop);
      };
      for (const e of user) window.addEventListener(e, stop, { passive: true });
      seen.observe(document.body, { childList: true, subtree: true });
      land();
      return stop;
    };
    let stop = go();
    const again = () => {
      stop();
      stop = go();
    };
    window.addEventListener("hashchange", again);
    return () => {
      stop();
      window.removeEventListener("hashchange", again);
    };
  }, [pathname]);
}

function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const tab = activeTab(pathname);
  useHashScroll(pathname);
  const { badges, offline } = useAdminData();
  return (
    <div className="drawer-view admin-view">
      <header className="drawer-head">
        <h1>Admin</h1>
        <p>{pageIntro[tab]}</p>
      </header>
      <nav className="admin-tabs" aria-label="Admin sections">
        {TABS.map((t) => (
          <Link key={t.tab} href={t.href} aria-current={t.tab === tab ? "page" : undefined}>
            {t.label}
            {badges[t.tab] > 0 && (
              <span className="admin-badge">
                {badges[t.tab]}
                <span className="sr-only"> need attention</span>
              </span>
            )}
          </Link>
        ))}
      </nav>
      {offline && <p className="notice bad">Backend offline. Start it with uvicorn.</p>}
      {children}
    </div>
  );
}

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <AdminDataProvider>
      <Shell>{children}</Shell>
    </AdminDataProvider>
  );
}
