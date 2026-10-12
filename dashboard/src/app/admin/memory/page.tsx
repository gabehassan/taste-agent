import Shell, { actingUser } from "@/app/admin/shell";
import MemoryView from "@/components/memory-view";
import { api } from "@/lib/api";
import { requireSession } from "@/lib/session";
import type { MemorySnapshot } from "@/lib/types";

export default async function AdminMemory() {
  await requireSession();
  const user = await actingUser();
  if (!user) return <Shell title="memory"><p className="muted">no users yet.</p></Shell>;
  const m = await api<MemorySnapshot>("/v1/me/memory", { userId: user.id });
  return (
    <Shell title={`memory · ${user.name || user.email}`}>
      <div className="admin-memory"><MemoryView m={m} admin /></div>
    </Shell>
  );
}
