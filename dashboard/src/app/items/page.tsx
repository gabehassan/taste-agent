import UserShell, { me } from "../user-shell";
import Block, { Grid } from "@/components/block";
import { Fade } from "@/components/motion";
import { relTime, userApi } from "@/lib/user";
import { saveUrl } from "../user-actions";

const FILTERS = [["", "all"], ["unread", "unread"], ["read", "read"], ["archived", "archived"]];

export default async function Items({ searchParams }: { searchParams: Promise<{ q?: string; status?: string; queued?: string }> }) {
  const { q, status, queued } = await searchParams;
  const m = await me();
  const qs = new URLSearchParams({ limit: "150" }); if (q) qs.set("q", q); if (status) qs.set("status", status);
  const { items, total } = await userApi(`/v1/items?${qs}`);
  return (
    <UserShell name={m.user.name || ""}>
      <Fade>
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-3 mb-8">
          <h1 className="display text-[28px]">{q ? q : "blocks"} <span className="mono u-faint align-middle ml-1">{q ? items.length : total}</span></h1>
          <div className="flex gap-4 text-sm">
            {FILTERS.map(([v, l]) => <a key={v} href={v ? `/items?status=${v}` : "/items"} className="hover:underline underline-offset-4" style={{ opacity: (status || "") === v ? 1 : 0.45 }}>{l}</a>)}
          </div>
          <form className="ml-auto w-64"><input name="q" placeholder="search" defaultValue={q} className="u-input" style={{ padding: "6px 10px", fontSize: 13 }} /></form>
        </div>
        <form action={saveUrl} className="flex gap-2 mb-10 max-w-2xl">
          <input name="url" placeholder="paste a link to add a block" required className="u-input" style={{ padding: "8px 10px", fontSize: 13 }} />
          <input name="note" placeholder="note" className="u-input" style={{ padding: "8px 10px", fontSize: 13, width: 180 }} />
          <button className="u-btn">add</button>
        </form>
        {queued && <p className="mono u-faint mb-6">on it. give it a minute.</p>}
      </Fade>
      {items.length === 0 ? <div className="u-muted py-16 text-center">nothing here.</div>
        : <Grid>{items.map((it: any, i: number) => <Block key={it.id} it={it} rel={relTime(it.created_at)} index={i} />)}</Grid>}
    </UserShell>
  );
}
