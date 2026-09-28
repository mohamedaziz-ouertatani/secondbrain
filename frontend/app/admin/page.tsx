"use client";

import { LibraryAdmin } from "@/components/admin/LibraryAdmin";
import { StatusCard } from "@/components/admin/StatusCard";

export default function AdminPage() {
  return (
    <div className="drawer-view admin-view">
      <header className="drawer-head">
        <h1>Admin</h1>
        <p>The cabinet itself: services, GPU and the index</p>
      </header>
      <StatusCard />
      <LibraryAdmin />
    </div>
  );
}
