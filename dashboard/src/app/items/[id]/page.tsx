import UserShell, { me } from "../../user-shell";
import { Fade, Stagger } from "@/components/motion";
import { relTime, userApi } from "@/lib/user";
import { setStatus } from "../../user-actions";

export default async function ItemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const m = await me();
  const it = await userApi(`/v1/items/${id}`);
  const thumb = it.meta?.thumbnail || it.media_urls?.[0];
  return (
    <UserShell name={m.user.name || ""}>
      <article className="pt-6 grid md:grid-cols-[1fr_280px] gap-10">
        <div>
          <Fade><div className="u-kicker mb-3">{it.kind} · {it.source} · {relTime(it.created_at)}</div></Fade>
          <Fade delay={0.05}><h1 className="display text-4xl md:text-5xl leading-[1.05] mb-3">{it.title}</h1></Fade>
          {it.author && <Fade delay={0.1}><div className="u-muted mb-6">{it.author}</div></Fade>}
          {thumb && <Fade delay={0.12}><img src={thumb} alt="" className="rounded-2xl mb-8 max-h-[420px] object-cover w-full" /></Fade>}
          <Fade delay={0.15}><p className="text-lg leading-relaxed mb-8">{it.summary}</p></Fade>
          <Stagger className="flex flex-col gap-4">
            {(it.snippets || []).map((s: string, i: number) => (
              <Fade key={i} className="u-card p-5"><p className="u-quote">“{s}”</p></Fade>
            ))}
          </Stagger>
          {it.why && <Fade delay={0.2} className="mt-8 u-muted italic">{it.why}</Fade>}
          {it.transcript && <details className="mt-8"><summary className="u-kicker cursor-pointer">transcript</summary><p className="mt-3 text-sm leading-relaxed whitespace-pre-wrap u-muted">{it.transcript}</p></details>}
          {it.raw_text && it.kind !== "screenshot" && <details className="mt-4"><summary className="u-kicker cursor-pointer">full text</summary><p className="mt-3 text-sm leading-relaxed whitespace-pre-wrap u-muted">{it.raw_text.slice(0, 30000)}</p></details>}
        </div>
        <aside className="flex flex-col gap-4">
          <Fade delay={0.2} className="u-card p-4 text-sm flex flex-col gap-2">
            {it.url && <a href={it.url} target="_blank" className="u-btn accent text-center">open original</a>}
            <div className="u-muted">{it.read_minutes} min · surfaced {it.surfaced_count}×</div>
            {it.note && <div><span className="u-kicker">your note</span><div className="mt-1">{it.note}</div></div>}
            {it.meta?.reactions?.length > 0 && <div><span className="u-kicker">you reacted</span><div className="mt-1">{it.meta.reactions.join(", ")}</div></div>}
            <div className="flex flex-wrap gap-1 mt-1">{(it.tags || []).map((t: string) => <span key={t} className="u-chip">{t}</span>)}</div>
          </Fade>
          <Fade delay={0.25} className="u-card p-4 flex gap-2 flex-wrap">
            {["unread", "read", "archived"].map(s => <form key={s} action={setStatus}><input type="hidden" name="id" value={it.id} /><input type="hidden" name="status" value={s} /><button className={`u-btn ${s === it.status ? "" : "soft"}`} style={{ padding: "6px 12px" }}>{s === "unread" ? "to read" : s}</button></form>)}
          </Fade>
        </aside>
      </article>
    </UserShell>
  );
}
