import Shell, { actingUser } from "../../shell";
import { api, fmtDate } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { deleteItem, patchItem } from "../../actions";

export default async function Item({ params }: { params: Promise<{ id: string }> }) {
  await requireSession();
  const { id } = await params;
  const user = await actingUser();
  const it = await api(`/v1/items/${id}`, { userId: user.id });
  return (
    <Shell title={it.title || it.url}>
      <div className="grid md:grid-cols-3 gap-6">
        <div className="md:col-span-2 flex flex-col gap-4">
          <div className="card"><div className="muted text-xs uppercase mb-1">summary</div><p>{it.summary}</p>{it.why && <p className="muted mt-2 text-sm">{it.why}</p>}</div>
          <div className="card"><div className="muted text-xs uppercase mb-1">snippets</div>{(it.snippets || []).map((s: string, i: number) => <blockquote key={i} className="border-l-2 border-neutral-700 pl-3 my-2 text-sm">{s}</blockquote>)}</div>
          {it.transcript && <details className="card"><summary className="cursor-pointer muted text-xs uppercase">transcript</summary><p className="text-sm whitespace-pre-wrap mt-2">{it.transcript}</p></details>}
          {it.raw_text && <details className="card"><summary className="cursor-pointer muted text-xs uppercase">extracted text</summary><p className="text-sm whitespace-pre-wrap mt-2">{it.raw_text.slice(0, 20000)}</p></details>}
        </div>
        <div className="flex flex-col gap-4">
          <div className="card text-sm flex flex-col gap-1">
            <div><span className="muted">kind</span> {it.kind} · <span className="muted">source</span> {it.source}</div>
            {it.author && <div><span className="muted">by</span> {it.author}</div>}
            {it.url && <a href={it.url} target="_blank" className="text-blue-400 break-all">{it.url}</a>}
            <div><span className="muted">saved</span> {fmtDate(it.created_at)}</div>
            <div><span className="muted">surfaced</span> {it.surfaced_count}× {it.last_surfaced_at && `(last ${fmtDate(it.last_surfaced_at)})`}</div>
            <div><span className="muted">read time</span> {it.read_minutes} min</div>
            {it.note && <div><span className="muted">note</span> {it.note}</div>}
            {it.meta?.reactions?.length > 0 && <div><span className="muted">reactions</span> {it.meta.reactions.join(", ")}</div>}
            <div>{(it.tags || []).map((t: string) => <span key={t} className="tag">{t}</span>)}</div>
          </div>
          {it.media_urls?.length > 0 && <div className="card grid grid-cols-2 gap-2">{it.media_urls.map((u: string) => <img key={u} src={u} className="rounded" alt="" />)}</div>}
          <div className="card flex gap-2 flex-wrap">
            {["unread", "read", "archived"].map(s => <form key={s} action={patchItem}><input type="hidden" name="uid" value={user.id} /><input type="hidden" name="id" value={it.id} /><input type="hidden" name="status" value={s} /><button className={s === it.status ? "" : "ghost"}>{s}</button></form>)}
            <form action={deleteItem}><input type="hidden" name="uid" value={user.id} /><input type="hidden" name="id" value={it.id} /><button className="danger">delete</button></form>
          </div>
        </div>
      </div>
    </Shell>
  );
}
