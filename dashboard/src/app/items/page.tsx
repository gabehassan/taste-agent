import UserShell, { me } from "../user-shell";
import ItemCard from "@/components/item-card";
import { Fade, Stagger } from "@/components/motion";
import { relTime, userApi } from "@/lib/user";
import { saveUrl } from "../user-actions";

const FILTERS = [["", "all"], ["unread", "to read"], ["read", "read"], ["archived", "archived"]];

export default async function Items({ searchParams }: { searchParams: Promise<{ q?: string; status?: string; queued?: string }> }) {
  const { q, status, queued } = await searchParams;
  const m = await me();
  const qs = new URLSearchParams({ limit: "120" }); if (q) qs.set("q", q); if (status) qs.set("status", status);
  const { items, total } = await userApi(`/v1/items?${qs}`);
  return (
    <UserShell name={m.user.name || ""}>
      <Fade><h1 className="display text-4xl pt-6 mb-6">library <span className="u-faint text-2xl">{total}</span></h1></Fade>
      <Fade delay={0.1} className="flex flex-wrap items-center gap-2 mb-6">
        {FILTERS.map(([v, l]) => <a key={v} href={v ? `/items?status=${v}` : "/items"} className="u-chip" style={{ background: (status || "") === v ? "var(--ink)" : undefined, color: (status || "") === v ? "var(--paper)" : undefined }}>{l}</a>)}
        <form className="ml-auto"><input name="q" placeholder="search everything" defaultValue={q} className="u-input" style={{ padding: "8px 12px", fontSize: 14 }} /></form>
      </Fade>
      <Fade delay={0.15}>
        <form action={saveUrl} className="u-card p-3 mb-8 flex gap-2 items-center">
          <input name="url" placeholder="paste a link to save it here instead" required className="u-input flex-1" style={{ padding: "8px 12px", fontSize: 14 }} />
          <input name="note" placeholder="note" className="u-input w-40" style={{ padding: "8px 12px", fontSize: 14 }} />
          <button className="u-btn">save</button>
        </form>
        {queued && <p className="u-muted text-sm mb-4">on it. it'll show up here in a minute.</p>}
      </Fade>
      {items.length === 0 ? <Fade className="u-card p-8 text-center u-muted">nothing here.</Fade> : (
        <Stagger className="columns-1 md:columns-2 lg:columns-3 gap-4" gap={0.04}>
          {items.map((it: any) => <ItemCard key={it.id} it={it} rel={relTime(it.created_at)} />)}
        </Stagger>
      )}
    </UserShell>
  );
}
