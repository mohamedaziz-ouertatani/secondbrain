import { ActionStrip } from "@/components/admin/ActionStrip";
import { GlanceTiles } from "@/components/admin/GlanceTiles";
import { NeedsAttention } from "@/components/admin/NeedsAttention";
import { SystemDetails } from "@/components/admin/SystemDetails";

export default function AdminOverview() {
  return (
    <>
      <NeedsAttention />
      <ActionStrip />
      <GlanceTiles />
      <SystemDetails />
    </>
  );
}
