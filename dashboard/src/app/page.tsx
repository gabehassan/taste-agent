import Link from "next/link";
import UserShell, { me } from "./user-shell";
import Block, { Grid, clean } from "@/components/block";
import Growth from "@/components/growth";
import { Fade } from "@/components/motion";
import { relTime, userApi } from "@/lib/user";
import { surfaceNow } from "./user-actions";

export default async function Home() {
  const m = await me();
  const u = m.user;
  const [{ items }, { surfaces }, mem, progress] = await Promise.all([userApi("/v1/items?limit=20"), userApi("/v1/surfaces?limit=3"), userApi("/v1/me/memory"), userApi("/v1/me/progress")]);
  const channels = (mem.tags || []).slice(0, 10);
  const pending = (m.plan?.slots || []).filter((s: any) => !s.done).map((s: any) => s.at.slice(11, 16));
  return (
    <UserShell name={u.name || ""}>
      <Fade>
        <div className="grid md:grid-cols-[1fr_320px] gap-10 items-start mb-14">
          <div>
            <h1 className="display text-[28px] md:text-[34px] max-w-3xl">{m.one_liner || "send me a few things and I'll start to get you."}</h1>
            <div className="mono u-faint mt-4 flex flex-wrap gap-x-5 gap-y-1">
              <span>{m.counts.items} blocks</span><span>{channels.length} channels</span><span>{m.counts.unread} unread</span>
              <span>{u.settings?.paused ? "paused" : pending.length ? `next drop ~${pending[0]}` : "no more drops today"}</span>
            </div>
          </div>
          <div className="md:justify-self-end">
            <form action={surfaceNow}><button className="u-btn soft">text me something now</button></form>
          </div>
        </div>
      </Fade>

      <Fade delay={0.03}><Growth p={progress} /></Fade>

      {channels.length > 0 && (
        <Fade delay={0.05}>
          <div className="hair pt-3 mb-12 flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <span className="mono u-faint self-center">channels</span>
            {channels.map((c: any) => <Link key={c.tag} href={`/items?q=${encodeURIComponent(c.tag)}`} className="hover:underline underline-offset-4">{c.tag} <span className="mono u-faint">{c.n}</span></Link>)}
          </div>
        </Fade>
      )}

      {surfaces.length > 0 && (
        <Fade delay={0.08}>
          <div className="hair pt-3 mb-12">
            <div className="mono u-faint mb-3">recently texted you</div>
            <div className="grid md:grid-cols-3 gap-5">
              {surfaces.map((s: any) => <div key={s.id} className="u-card p-4"><p className="u-quote line-clamp-5">{clean(s.text.split("\n")[0])}</p><div className="mono u-faint mt-3">{relTime(s.created_at)}</div></div>)}
            </div>
          </div>
        </Fade>
      )}

      <div className="hair pt-3">
        <div className="flex items-baseline justify-between mb-5">
          <span className="mono u-faint">latest</span>
          <Link href="/items" className="text-sm u-muted hover:underline underline-offset-4">all blocks</Link>
        </div>
        {items.length === 0 ? <div className="u-muted py-16 text-center">nothing yet. text me a link.</div>
          : <Grid>{items.map((it: any, i: number) => <Block key={it.id} it={it} rel={relTime(it.created_at)} index={i} />)}</Grid>}
      </div>
    </UserShell>
  );
}
