import Shell, { actingUser } from "@/app/admin/shell";
import { api, fmtDate } from "@/lib/api";
import { requireSession } from "@/lib/session";
import type { ProfileResponse } from "@/lib/types";
import { refreshProfile, surfaceNow } from "@/app/admin/actions";

export default async function ProfilePage() {
  await requireSession();
  const user = await actingUser();
  if (!user) return <Shell title="profile"><p className="muted">no users yet.</p></Shell>;
  const { profile, history } = await api<ProfileResponse>("/v1/profile", { userId: user.id });
  return (
    <Shell title={`taste profile · ${user.name || user.email}`}>
      <div className="flex gap-2 mb-4">
        <form action={refreshProfile}><input type="hidden" name="uid" value={user.id} /><button>rebuild now</button></form>
        <form action={surfaceNow}><input type="hidden" name="uid" value={user.id} /><button className="ghost">text them a snippet now</button></form>
      </div>
      {!profile ? <p className="muted">no profile yet. it builds after the first few items.</p> : (
        <div className="grid md:grid-cols-3 gap-6">
          <div className="md:col-span-2 card"><div className="text-lg mb-3">{profile.one_liner}</div><p className="whitespace-pre-wrap text-sm leading-relaxed">{profile.text}</p><div className="muted text-xs mt-3">built {fmtDate(profile.created_at)} from {profile.item_count} items</div></div>
          <div className="flex flex-col gap-4">
            <div className="card"><div className="muted text-xs uppercase mb-2">observations</div><ul className="text-sm flex flex-col gap-2">{profile.observations.map((o, i) => <li key={i}>{o}</li>)}</ul></div>
            <div className="card"><div className="muted text-xs uppercase mb-2">history</div>{history.map(h => <div key={h.id} className="text-xs muted">{fmtDate(h.created_at)} · {h.item_count} items</div>)}</div>
          </div>
        </div>
      )}
    </Shell>
  );
}
