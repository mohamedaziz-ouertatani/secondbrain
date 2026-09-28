"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { type DocumentRow, getJSON } from "./api";

type Library = { docs: DocumentRow[] | null; error: string | null; reload: () => void };

/** All documents; shared shape for the rail and the drawer. */
export function useLibrary(): Library {
  const [docs, setDocs] = useState<DocumentRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    getJSON<DocumentRow[]>("/documents")
      .then((d) => {
        setDocs(d);
        setError(null);
      })
      .catch(() => setError("The library backend isn't answering."));
  }, []);
  useEffect(() => {
    reload();
    const onSeen = () => setDocs((d) => (d ? [...d] : d)); // re-render new marks
    window.addEventListener("sb:seen", onSeen);
    return () => window.removeEventListener("sb:seen", onSeen);
  }, [reload]);
  return { docs, error, reload };
}

/** The open drawer (?m=<module>); null means all drawers. */
export function useDrawer(): string | null {
  return useSearchParams().get("m");
}

export function drawerHref(base: string, course: string | null): string {
  return course ? `${base}?m=${encodeURIComponent(course)}` : base;
}
