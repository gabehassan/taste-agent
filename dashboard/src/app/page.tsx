import Link from "next/link";
import UserShell, { me } from "./user-shell";
import Block, { Grid, clean } from "@/components/block";
import Growth from "@/components/growth";
import { Fade } from "@/components/motion";
import { relTime, userApi } from "@/lib/user";
import { surfaceNow } from "./user-actions";

function greeting(tz: string) {
  const h = Number(new Intl.DateTimeFormat("en-US", { hour: "numeric", hour12: false, timeZone: tz }).format(new Date()));
  return h < 5 ? "still up" : h < 12 ? "morning" : h < 17 ? "afternoon" : h < 22 ? "evening" : "late";
}
const nice = (hhmm: string) => { const [h, m] = hhmm.split(":").map(Number); return `${((h + 11) % 12) + 1}${m ? ":" + String(m).padStart(2, "0") : ""}${h < 12 ? "am" : "pm"}`; };
const hours = (min: number) => min < 60 ? `${min} minutes` : min < 120 ? "about an hour" : `about ${Math.round(min / 60)} hours`;

export default async function Home() {
  const m = await me();
  const u = m.user;
  const [{ items }, { surfaces }, mem, progress] = await Promise.all([userApi("/v1/items?limit=20"), userApi("/v1/surfaces?limit=2"), userApi("/v1/me/memory"), userApi("/v1/me/progress")]);
  const channels = (mem.tags || []).slice(0, 8);
  const pending = (m.plan?.slots || []).filter((s: any) => !s.done).map((s: any) => s.at.slice(11, 16));
  const first = (u.name || "").split(" ")[0].toLowerCase();
  const n = m.counts.items;

  // one honest sentence about the state of things
  const status = u.settings?.paused ? "I'm paused. say resume whenever."
    : n === 0 ? "nothing here yet. text me anything you want to come back to."
    : pending.length ? `I'll text you something around ${nice(pending[0])}.`
    : "that's it from me today.";
  const facts: string[] = [];
  if (m.unread_minutes > 0) facts.push(`${hours(m.unread_minutes)} of reading waiting`);
  if (m.streak_days >= 2) facts.push(`${m.streak_days} days in a row`);
  if (m.counts.read > 0) facts.push(`${m.counts.read} finished`);

  return (
    <UserShell name={u.name || ""}>
      <Fade>
        <div className="mb-10 max-w-3xl">
          <div className="u-muted text-[15px] mb-2">{greeting(u.tz)}{first ? `, ${first}` : ""}.</div>
          <h1 className="display text-[26px] md:text-[32px]">{m.one_liner || (n === 0 ? "I don't know you yet." : n < 5 ? `I've read ${n} thing${n === 1 ? "" : "s"} you sent. a few more and I'll start to have opinions.` : "still working you out.")}</h1>
          <p className="text-[15px] mt-4 u-muted">{status}{facts.length ? ` ${facts.join(" · ")}.` : ""}{n > 0 && !u.settings?.paused && <> <form action={surfaceNow} className="inline"><button className="underline underline-offset-4 hover:opacity-70">or send something now</button></form></>}</p>
        </div>
      </Fade>

      <Fade delay={0.03}><Growth p={progress} /></Fade>

      {m.forgotten && (
        <Fade delay={0.05}>
          <Link href={`/items/${m.forgotten.id}`} className="block hair py-4 mb-10 max-w-3xl group">
            <div className="mono u-faint mb-1">you saved this {relTime(m.forgotten.created_at)} and haven't opened it</div>
            <div className="text-[15px] group-hover:underline underline-offset-4">{m.forgotten.title}</div>
          </Link>
        </Fade>
      )}

      {surfaces.length > 0 && (
        <Fade delay={0.06}>
          <div className="mb-12 max-w-xl">
            <div className="mono u-faint mb-3">last texts</div>
            <div className="flex flex-col gap-1.5">
              {surfaces.map((s: any) => (
                <div key={s.id} className="flex justify-start"><div className="max-w-[85%] px-3.5 py-2 text-[15px] leading-snug" style={{ background: "var(--paper-2)", borderRadius: 18, borderBottomLeftRadius: 4 }}>{clean(s.text.split("\n")[0])}<span className="mono u-faint block mt-1">{relTime(s.created_at)}</span></div></div>
              ))}
            </div>
          </div>
        </Fade>
      )}

      {channels.length > 0 && (
        <Fade delay={0.08}>
          <div className="mb-8 flex flex-wrap gap-x-5 gap-y-1 text-sm">
            <span className="u-faint">you keep coming back to</span>
            {channels.map((c: any) => <Link key={c.tag} href={`/items?q=${encodeURIComponent(c.tag)}`} className="hover:underline underline-offset-4">{c.tag}</Link>)}
          </div>
        </Fade>
      )}

      <div className="hair pt-3">
        <div className="flex items-baseline justify-between mb-5">
          <span className="u-faint text-sm">latest</span>
          <Link href="/items" className="text-sm u-muted hover:underline underline-offset-4">everything</Link>
        </div>
        {items.length === 0 ? <div className="u-muted py-16 text-center">nothing yet. text me a link.</div>
          : <Grid>{items.map((it: any, i: number) => <Block key={it.id} it={it} rel={relTime(it.created_at)} index={i} />)}</Grid>}
      </div>
    </UserShell>
  );
}
