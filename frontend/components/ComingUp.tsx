"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ItemRow } from "@/components/planner/ItemRow";
import { plannerHref, useUpcoming } from "@/lib/planner";
import { drawerHref } from "@/lib/useLibrary";

const SHOWN = 5;

/** Overdue to-dos and the next 7 days; hidden when there's nothing, so the desk stays quiet. */
export function ComingUp({ drawer }: { drawer: string | null }) {
  const items = useUpcoming(drawer, 7);
  const router = useRouter();
  if (!items || items.length === 0) return null;
  return (
    <section className="coming-up" aria-label="Coming up">
      <h2 className="stack-label">Coming up{drawer ? ` in ${drawer}` : ""}</h2>
      <ul className="plan-list card">
        {items.slice(0, SHOWN).map((i) => (
          <ItemRow key={i.id} item={i} onOpen={(it) => router.push(plannerHref(it.id, drawer))} />
        ))}
      </ul>
      {items.length > SHOWN && (
        <Link className="coming-more" href={drawerHref("/planner", drawer)}>
          {items.length - SHOWN} more in the planner
        </Link>
      )}
    </section>
  );
}
