import Link from "next/link";
import Shell, { actingUser } from "../shell";
import { api, fmtDate } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { ingestUrl } from "../actions";

export default async function Items({ searchParams }: { searchParams: Promise<{ q?: string; status?: string }> }) {
  await requireSession();
  const { q, status } = await searchParams;
  const user = await actingUser();
  if (!user) return <Shell title="items"><p className="muted">no users yet. create one under users.</p></Shell>;
  const qs = new URLSearchParams({ limit: "100" }); if (q) qs.set("q", q); if (status) qs.set("status", status);
  const { items, total } = await api(`/v1/items?${qs}`, { userId: user.id });
  return (
    <Shell title={`items · ${user.name || user.email}`}>
      <div className="flex gap-3 mb-4 items-end flex-wrap">
        <form className="flex gap-2"><input name="q" placeholder="search" defaultValue={q} /><select name="status" defaultValue={status || ""}><option value="">all</option><option>unread</option><option>read</option><option>archived</option><option>pending</option></select><button className="ghost">filter</button></form>
        <form action={ingestUrl} className="flex gap-2 ml-auto"><input type="hidden" name="uid" value={user.id} /><input name="url" placeholder="https://… (save for this user)" required className="w-72" /><input name="note" placeholder="note" /><label className="text-xs muted flex items-center gap-1"><input type="checkbox" name="notify" /> text them</label><button>save</button></form>
      </div>
      <div className="muted text-sm mb-2">{total} total</div>
      <table className="w-full"><thead><tr><th>title</th><th>kind</th><th>tags</th><th>status</th><th>saved</th></tr></thead><tbody>
        {items.map((i: any) => (
          <tr key={i.id}><td><Link href={`/items/${i.id}`} className="hover:underline">{i.title || i.url}</Link><div className="muted text-xs">{i.source}</div></td>
          <td>{i.kind}</td><td>{(i.tags || []).slice(0, 5).map((t: string) => <span key={t} className="tag">{t}</span>)}</td><td>{i.status}</td><td className="muted whitespace-nowrap">{fmtDate(i.created_at)}</td></tr>
        ))}
      </tbody></table>
    </Shell>
  );
}
