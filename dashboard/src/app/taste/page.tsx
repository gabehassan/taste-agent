import UserShell, { me } from "../user-shell";
import { Fade } from "@/components/motion";
import type { ProfileResponse } from "@/lib/types";
import { relTime, userApi } from "@/lib/user";
import { rebuildProfile } from "../user-actions";

export default async function Taste() {
  const m = await me();
  const { profile, history } = await userApi<ProfileResponse>("/v1/profile");
  return (
    <UserShell name={m.user.name || ""}>
      <Fade>
        {!profile ? <div className="u-muted py-16">not enough yet. send me five or six things and I&apos;ll write you up.</div> : (
          <div className="grid md:grid-cols-[minmax(0,640px)_320px] gap-16">
            <div>
              <div className="mono u-faint mb-4">taste · v{history.length} · {relTime(profile.created_at)} · from {profile.item_count} blocks</div>
              <h1 className="display text-[28px] md:text-[34px] mb-10">{profile.one_liner}</h1>
              <div className="flex flex-col gap-5 text-[16px] leading-relaxed">
                {profile.text.split(/\n\s*\n/).map((p, i) => <p key={i}>{p}</p>)}
              </div>
              <form action={rebuildProfile} className="mt-10"><button className="u-btn soft">rethink me</button></form>
            </div>
            <aside className="md:pt-10">
              <div className="mono u-faint mb-3">observations</div>
              <ol className="flex flex-col">
                {profile.observations.map((o, i) => <li key={i} className="hair py-3 flex gap-4 text-sm"><span className="mono u-faint w-5 shrink-0">{String(i + 1).padStart(2, "0")}</span><span>{o}</span></li>)}
              </ol>
            </aside>
          </div>
        )}
      </Fade>
    </UserShell>
  );
}
