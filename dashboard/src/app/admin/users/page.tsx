import Shell from "@/app/admin/shell";
import { api, fmtDate, fmtMoney } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { addHandle, createKey, createUser, revokeKey, setUserCap, toggleUser } from "@/app/admin/actions";

export default async function Users({ searchParams }: { searchParams: Promise<{ newkey?: string }> }) {
  await requireSession();
  const { newkey } = await searchParams;
  const { users } = await api("/v1/admin/users");
  return (
    <Shell title="users">
      {newkey && <div className="card mb-6 border-green-800"><div className="muted text-xs uppercase">new key (shown once, copy it now)</div><code className="block mt-1 break-all select-all">{newkey}</code></div>}
      <div className="flex flex-col gap-4 mb-8">
        {users.map((u: any) => (
          <div key={u.id} className="card">
            <div className="flex items-baseline gap-3 flex-wrap">
              <div className="text-lg">{u.name || "(no name)"}</div><div className="muted text-sm">{u.email}</div>
              <span className="pill" style={{ background: u.status === "active" ? "#14532d" : "#7f1d1d" }}>{u.status}</span>
              <span className="pill bg-neutral-800">{u.role}</span><span className="muted text-sm">{u.tz}</span>
              <span className="muted text-sm ml-auto">{u.items} items · {fmtMoney(u.spend_today)} today · {fmtMoney(u.spend_month)} month · cap {fmtMoney(u.settings?.daily_spend_cap_usd ?? "2")}/day</span>
            </div>
            <div className="grid md:grid-cols-3 gap-4 mt-4 text-sm">
              <div>
                <div className="muted text-xs uppercase mb-1">handles</div>
                {(u.handles || []).map((h: any) => <div key={h.id}>{h.address} <span className="muted text-xs">{(h.capabilities || []).join(",")} {h.last_seen_at && `· seen ${fmtDate(h.last_seen_at)}`}</span></div>)}
                <form action={addHandle} className="flex gap-1 mt-2"><input type="hidden" name="uid" value={u.id} /><input name="address" placeholder="email or +1…" required /><button className="ghost">add</button></form>
              </div>
              <div>
                <div className="muted text-xs uppercase mb-1">api keys</div>
                {(u.keys || []).filter((k: any) => !k.revoked_at).map((k: any) => <div key={k.id} className="flex gap-2 items-center"><code>{k.prefix}…</code><span className="muted text-xs">{k.name} · {k.scopes.join(",")} {k.last_used_at && `· used ${fmtDate(k.last_used_at)}`}</span><form action={revokeKey}><input type="hidden" name="kid" value={k.id} /><button className="danger text-xs px-2 py-0.5">revoke</button></form></div>)}
                <form action={createKey} className="flex gap-1 mt-2"><input type="hidden" name="uid" value={u.id} /><input name="name" placeholder="name" className="w-24" /><select name="scope"><option value="transport">transport</option><option value="user">user</option><option value="admin">admin</option></select><button className="ghost">new key</button></form>
              </div>
              <div className="flex flex-col gap-2">
                <form action={setUserCap} className="flex gap-1"><input type="hidden" name="uid" value={u.id} /><input name="cap" type="number" step="0.5" min="0" defaultValue={u.settings?.daily_spend_cap_usd ?? 2} className="w-24" /><button className="ghost">set $/day cap</button></form>
                <form action={toggleUser}><input type="hidden" name="uid" value={u.id} /><input type="hidden" name="status" value={u.status === "active" ? "disabled" : "active"} /><button className={u.status === "active" ? "danger" : ""}>{u.status === "active" ? "disable" : "enable"}</button></form>
              </div>
            </div>
          </div>
        ))}
      </div>
      <form action={createUser} className="card flex gap-2 flex-wrap items-end">
        <div className="w-full font-medium">add user</div>
        <input name="name" placeholder="name" required /><input name="email" placeholder="email" type="email" /><input name="handles" placeholder="imessage handles, comma separated" className="w-80" />
        <select name="role"><option value="user">user</option><option value="admin">admin</option></select><input name="tz" defaultValue="America/Detroit" className="w-40" /><button>create</button>
      </form>
    </Shell>
  );
}
