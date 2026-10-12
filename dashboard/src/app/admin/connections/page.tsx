import Shell, { actingUser } from "@/app/admin/shell";
import { api, fmtDate } from "@/lib/api";
import { requireSession } from "@/lib/session";
import type { Connections as ConnectionList } from "@/lib/types";
import { addConnection, deleteConnection, syncConnection } from "@/app/admin/actions";

export default async function Connections() {
  await requireSession();
  const user = await actingUser();
  if (!user) return <Shell title="connections"><p className="muted">no users yet.</p></Shell>;
  const { connections, types } = await api<ConnectionList>("/v1/connections", { userId: user.id });
  return (
    <Shell title={`connections · ${user.name || user.email}`}>
      <table className="w-full mb-8"><thead><tr><th>type</th><th>config</th><th>status</th><th>last sync</th><th></th></tr></thead><tbody>
        {connections.map(c => (
          <tr key={c.id}><td>{types[c.type]?.label ?? c.type}</td><td className="text-sm">{Object.entries(c.config).map(([k, v]) => `${k}: ${v}`).join(", ")}</td>
          <td>{c.status}{c.last_error && <div className="text-red-400 text-xs">{c.last_error}</div>}</td><td className="muted">{fmtDate(c.last_synced_at) || "never"}</td>
          <td className="flex gap-2"><form action={syncConnection}><input type="hidden" name="uid" value={user.id} /><input type="hidden" name="cid" value={c.id} /><button className="ghost">sync</button></form><form action={deleteConnection}><input type="hidden" name="uid" value={user.id} /><input type="hidden" name="cid" value={c.id} /><button className="danger">remove</button></form></td></tr>
        ))}
        {connections.length === 0 && <tr><td colSpan={5} className="muted">none yet</td></tr>}
      </tbody></table>
      <div className="grid md:grid-cols-3 gap-4">
        {Object.entries(types).map(([type, t]) => (
          <form key={type} action={addConnection} className="card flex flex-col gap-2">
            <div className="font-medium">{t.label}</div>
            <input type="hidden" name="uid" value={user.id} /><input type="hidden" name="type" value={type} />
            {t.config.map(k => <input key={k} name={`cfg_${k}`} placeholder={k} required />)}
            <button>connect</button>
            <div className="muted text-xs">{type === "letterboxd" ? "public diary via RSS, polled hourly" : type === "goodreads" ? "numeric user id from your profile URL; shelves via RSS" : "any feed; new entries get saved and digested (no texts)"}</div>
          </form>
        ))}
        <div className="card muted text-sm"><div className="font-medium text-neutral-100 mb-1">coming later</div>TikTok favorites, Instagram saved, X bookmarks: via their data-export uploads.</div>
      </div>
    </Shell>
  );
}
