import Link from "next/link";
import { redirect } from "next/navigation";
import UserShell, { me } from "./user-shell";
import { Fade } from "@/components/motion";
import TasteMark from "@/components/taste-mark";
import DailyPicks, { type DailyPick } from "@/components/daily-picks";
import { onboardingConfig, messageLink } from "@/lib/onboarding";
import { userApi, userKey } from "@/lib/user";

type Today = { picks: DailyPick[]; finished_week: number; finished_total: number; available: number; memories: {id: string; text: string}[] };

export default async function Home() {
  if (!(await userKey())) redirect("/start");
  const m = await me();
  const contact = await onboardingConfig();
  const today = await userApi<Today>("/v1/me/today");
  const date = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: m.user.tz || "UTC" }).format(new Date());
  const first = (m.user.name || "").split(" ")[0];
  const milestone = [1, 3, 7, 15, 30, 60, 100].find(n => n > today.finished_total) || Math.ceil((today.finished_total + 1) / 50) * 50;
  return <UserShell name={m.user.name || ""}>
    <Fade><section className="today-intro">
      <div className="mono u-muted">{date.toLowerCase()} <span className="mx-2">·</span> a little room for curiosity</div>
      <div className="intro-heading"><div>
        <p className="u-muted mb-3">{first ? `hey, ${first.toLowerCase()}.` : "hey, you."}</p>
        <h1 className="display">less collecting.<br /><span className="u-muted">more coming back.</span></h1>
        <p className="intro-copy">{today.picks.length ? "a few things from your world, picked for a moment like this. start with one. the rest can wait." : "a place for the things that stay with you. send taste something you love, and we’ll find our way back to it."}</p>
      </div><TasteMark /></div>
    </section></Fade>
    <Fade delay={0.05}>
      <div className="section-label"><h2>on your mind, again</h2><span className="mono u-muted">{today.picks.length ? `${today.picks.length} small invitations` : "your first invitation"}</span></div>
      {today.picks.length ? <DailyPicks picks={today.picks} /> : <div className="quiet-empty"><TasteMark small /><h3>nothing to catch up on.</h3><p>{m.counts.items ? "your collection is still here whenever you want it. finished and snoozed things can rest." : "text taste a link, a screenshot, or the thing you keep thinking about."}</p><Link href={m.counts.items ? "/items" : "/start"} className="u-btn inline-block mt-5">{m.counts.items ? "visit your collection" : "open Messages"}</Link></div>}
    </Fade>
    <Fade delay={0.1}><div className="today-bottom">
      <section className="return-progress">
        <div className="mono u-muted mb-5">a collection, lived in</div>
        <div className="return-number">{today.finished_total}<span>things you came back to</span></div>
        <div className="return-track" role="progressbar" aria-label="Finished items" aria-valuenow={today.finished_total} aria-valuemin={0} aria-valuemax={milestone}><span style={{width: `${Math.min(today.finished_total / milestone, 1) * 100}%`}} /></div>
        <p className="text-xs u-muted mt-3">{today.finished_week ? `${today.finished_week} finished this week. a little more of your collection became part of your life.` : "no streaks to keep. just good things to make time for."}</p>
      </section>
      <section className="taste-note">
        <div className="mono u-muted mb-5">a note from taste</div>
        <p>{m.one_liner || "I’m still getting to know your world. tell me what caught your eye, and what didn’t. both help."}</p>
        <Link href="/memory" className="text-xs underline underline-offset-4 mt-5 inline-block">what I’m remembering <span aria-hidden="true">↗</span></Link>
      </section>
    </div></Fade>
    {contact?.phone && <section className="taste-conversation"><TasteMark small /><div><h2 className="display text-xl">leave with a thought.</h2><p className="u-muted text-sm mt-2">something clicked? something felt off? tell taste. that’s where it gets interesting.</p></div><a className="u-btn" href={messageLink(contact.phone)}>talk to taste ↗</a></section>}
    <div className="today-footer"><span>your taste is allowed to change.</span><Link href="/items">everything you’ve kept <span aria-hidden="true">↗</span></Link></div>
  </UserShell>;
}
