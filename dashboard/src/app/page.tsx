import Link from "next/link";
import UserShell, { me } from "./user-shell";
import ItemCard from "@/components/item-card";
import { Fade, Stagger, Words } from "@/components/motion";
import { relTime, userApi } from "@/lib/user";
import { surfaceNow } from "./user-actions";

function greeting(tz: string) {
  const h = Number(new Intl.DateTimeFormat("en-US", { hour: "numeric", hour12: false, timeZone: tz }).format(new Date()));
  return h < 5 ? "still up?" : h < 12 ? "morning." : h < 17 ? "afternoon." : h < 22 ? "evening." : "late one.";
}

export default async function Home() {
  const m = await me();
  const u = m.user;
  const [{ items }, { surfaces }] = await Promise.all([userApi("/v1/items?limit=12"), userApi("/v1/surfaces?limit=3")]);
  const pending = (m.plan?.slots || []).filter((s: any) => !s.done).map((s: any) => s.at.slice(11, 16));
  const first = (u.name || "").split(" ")[0];
  return (
    <UserShell name={u.name || ""}>
      <section className="pt-10 pb-12">
        <Fade><div className="u-kicker mb-3">{greeting(u.tz)} {first}</div></Fade>
        <h1 className="display text-5xl md:text-6xl leading-[1.05] max-w-3xl">
          <Words text={m.one_liner || "send me a few things and I'll start to get you."} />
        </h1>
        <Fade delay={0.5} className="mt-6 flex flex-wrap items-center gap-3 text-sm u-muted">
          <span>{m.counts.items} saved</span><span>·</span><span>{m.counts.unread} to come back to</span><span>·</span>
          <span>{u.settings?.paused ? "paused" : pending.length ? `next drop around ${pending[0]}` : "no more drops today"}</span>
          <form action={surfaceNow}><button className="u-btn soft ml-2">text me something now</button></form>
        </Fade>
      </section>

      {surfaces.length > 0 && (
        <section className="mb-12">
          <Fade delay={0.2}><div className="u-kicker mb-3">recently texted you</div></Fade>
          <Stagger className="grid md:grid-cols-3 gap-4">
            {surfaces.map((s: any) => (
              <Fade key={s.id} className="u-card p-4"><p className="u-quote line-clamp-5">{s.text.split("\n")[0]}</p><div className="u-faint text-xs mt-3">{relTime(s.created_at)}</div></Fade>
            ))}
          </Stagger>
        </section>
      )}

      <section>
        <div className="flex items-baseline justify-between mb-3">
          <Fade><div className="u-kicker">latest</div></Fade>
          <Link href="/items" className="text-sm u-muted hover:underline">everything →</Link>
        </div>
        {items.length === 0 ? (
          <Fade className="u-card p-8 text-center u-muted">nothing yet. text me a link.</Fade>
        ) : (
          <Stagger className="columns-1 md:columns-2 lg:columns-3 gap-4">
            {items.map((it: any) => <ItemCard key={it.id} it={it} rel={relTime(it.created_at)} />)}
          </Stagger>
        )}
      </section>
    </UserShell>
  );
}
