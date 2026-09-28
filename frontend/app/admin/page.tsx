"use client";

import { InsightsCard } from "@/components/admin/InsightsCard";
import { LibraryAdmin } from "@/components/admin/LibraryAdmin";
import { SettingsCard } from "@/components/admin/SettingsCard";
import { StatusCard } from "@/components/admin/StatusCard";

export default function AdminPage() {
  return (
    <div className="drawer-view admin-view">
      <header className="drawer-head">
        <h1>Admin</h1>
        <p>The cabinet itself: services, usage, the index and settings</p>
      </header>
      <StatusCard />
      <InsightsCard />
      <LibraryAdmin />
      <SettingsCard />
    </div>
  );
}
