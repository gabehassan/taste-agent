import Link from "next/link";
import { api } from "@/lib/api";
import { currentUserId } from "@/lib/session";
import { pickUser } from "@/app/admin/actions";

const NAV = [["/admin", "overview"], ["/admin/items", "items"], ["/admin/profile", "profile"], ["/admin/memory", "memory"], ["/admin/connections", "connections"], ["/admin/users", "users"], ["/admin/settings", "settings"], ["/admin/logs", "logs"]];

export default async function Shell({ children, title }: { children: React.ReactNode; title: string }) {
  const [{ users }, uid] = await Promise.all([api("/v1/admin/users"), currentUserId()]);
  const current = users.find((u: any) => u.id === uid) ?? users[0];
  return (
    <div className="flex min-h-screen">
      <aside className="w-52 shrink-0 border-r border-neutral-800 p-4 flex flex-col gap-1">
        <div className="text-lg font-semibold mb-3">taste <span className="muted text-xs">admin</span></div>
        {NAV.map(([href, label]) => (
          <Link key={href} href={href} className="rounded px-2 py-1 text-sm text-neutral-300 hover:bg-neutral-800">{label}</Link>
        ))}
        <form action={pickUser} className="mt-auto flex flex-col gap-2">
          <label className="text-xs muted">acting as</label>
          <select name="uid" defaultValue={current?.id} className="w-full">
            {users.map((u: any) => <option key={u.id} value={u.id}>{u.name || u.email || u.id.slice(0, 8)}</option>)}
          </select>
          <button className="ghost">switch</button>
        </form>
        <form action="/api/admin-logout" method="post"><button className="ghost w-full mt-2">log out</button></form>
      </aside>
      <main className="flex-1 p-8 max-w-6xl">
        <h1 className="text-2xl font-semibold mb-6">{title}</h1>
        {children}
      </main>
    </div>
  );
}

export async function actingUser() {
  const [{ users }, uid] = await Promise.all([api("/v1/admin/users"), currentUserId()]);
  return users.find((u: any) => u.id === uid) ?? users[0] ?? null;
}
