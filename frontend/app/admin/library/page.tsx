import { LibraryAdmin } from "@/components/admin/LibraryAdmin";
import { SyncCard } from "@/components/admin/SyncCard";
import { TagsCard } from "@/components/admin/TagsCard";

export default function AdminLibrary() {
  return (
    <>
      <LibraryAdmin />
      <TagsCard />
      <SyncCard />
    </>
  );
}
