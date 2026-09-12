import Shell from "@/app/admin/shell";
import { api, fmtDate } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { retryJob } from "@/app/admin/actions";

export default async function Logs() {
  await requireSession();
  const [{ jobs }, { messages }, { audit }, usage] = await Promise.all([
    api("/v1/admin/jobs?limit=60"), api("/v1/admin/messages?limit=60"), api("/v1/admin/audit?limit=40"), api("/v1/admin/usage?days=30"),
  ]);
  return (
    <Shell title="logs">
      <div className="grid md:grid-cols-2 gap-6">
        <div className="card"><div className="font-medium mb-2">messages</div><div className="flex flex-col gap-2 max-h-[32rem] overflow-auto text-sm">
          {messages.map((m: any) => <div key={m.id} className={`rounded px-3 py-2 ${m.direction === "in" ? "bg-neutral-800" : "bg-blue-950"}`}><div className="muted text-xs">{m.direction} · {m.kind} · {m.status} · {m.name} · {fmtDate(m.created_at)}</div><div className="whitespace-pre-wrap">{m.kind === "reaction" ? `${m.meta?.emoji ?? m.meta?.reaction} on ${m.meta?.target_external_id}` : m.text}</div></div>)}
        </div></div>
        <div className="card"><div className="font-medium mb-2">jobs</div><table className="w-full"><thead><tr><th>id</th><th>type</th><th>status</th><th>attempts</th><th>when</th><th></th></tr></thead><tbody>
          {jobs.map((j: any) => <tr key={j.id}><td>{j.id}</td><td>{j.type}</td><td>{j.status}{j.error && <div className="text-red-400 text-xs max-w-xs truncate" title={j.error}>{j.error}</div>}</td><td>{j.attempts}</td><td className="muted whitespace-nowrap">{fmtDate(j.created_at)}</td><td>{j.status === "failed" && <form action={retryJob}><input type="hidden" name="jid" value={j.id} /><button className="ghost text-xs">retry</button></form>}</td></tr>)}
        </tbody></table></div>
        <div className="card"><div className="font-medium mb-2">spend by model (30d)</div><table className="w-full"><thead><tr><th>model</th><th>kind</th><th>calls</th><th>in</th><th>out</th><th>cost</th></tr></thead><tbody>
          {usage.by_model.map((r: any, i: number) => <tr key={i}><td>{r.model}</td><td>{r.kind}</td><td>{r.calls}</td><td>{r.input_tokens}</td><td>{r.output_tokens}</td><td>${Number(r.cost).toFixed(3)}</td></tr>)}
        </tbody></table>
        <div className="font-medium mt-4 mb-2">by day</div><div className="text-xs muted flex flex-wrap gap-2">{usage.by_day.map((d: any) => <span key={d.day}>{String(d.day).slice(0, 10)}: ${Number(d.cost).toFixed(2)}</span>)}</div></div>
        <div className="card"><div className="font-medium mb-2">audit</div><div className="text-xs flex flex-col gap-1">{audit.map((a: any) => <div key={a.id}><span className="muted">{fmtDate(a.created_at)}</span> {a.action} <span className="muted">{JSON.stringify(a.detail)}</span></div>)}</div></div>
      </div>
    </Shell>
  );
}
