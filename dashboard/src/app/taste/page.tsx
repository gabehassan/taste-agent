import UserShell, { me } from "../user-shell";
import { Fade, Stagger, Words } from "@/components/motion";
import { relTime, userApi } from "@/lib/user";
import { rebuildProfile } from "../user-actions";

export default async function Taste() {
  const m = await me();
  const { profile, history } = await userApi("/v1/profile");
  return (
    <UserShell name={m.user.name || ""}>
      <div className="pt-8">
        <Fade><div className="u-kicker mb-3">your taste, as far as I can tell</div></Fade>
        {!profile ? (
          <Fade className="u-card p-8 u-muted">not enough yet. send me five or six things and I'll write you up.</Fade>
        ) : (
          <div className="grid md:grid-cols-[1fr_320px] gap-10">
            <div>
              <h1 className="display text-4xl md:text-5xl leading-[1.08] mb-8"><Words text={profile.one_liner} /></h1>
              <Stagger className="flex flex-col gap-6 text-[1.05rem] leading-relaxed max-w-2xl">
                {profile.text.split(/\n\s*\n/).map((p: string, i: number) => <Fade key={i}><p>{p}</p></Fade>)}
              </Stagger>
              <Fade delay={0.4} className="u-faint text-xs mt-8">written {relTime(profile.created_at)} from {profile.item_count} things</Fade>
            </div>
            <aside>
              <Fade delay={0.2}><div className="u-kicker mb-3">things I've noticed</div></Fade>
              <Stagger className="flex flex-col gap-3" gap={0.08}>
                {profile.observations.map((o: string, i: number) => <Fade key={i} className="u-card p-4 u-quote text-base">{o}</Fade>)}
              </Stagger>
              <form action={rebuildProfile} className="mt-6"><button className="u-btn soft">rethink me</button></form>
              {history.length > 1 && <div className="u-faint text-xs mt-4">{history.length} versions so far</div>}
            </aside>
          </div>
        )}
      </div>
    </UserShell>
  );
}
