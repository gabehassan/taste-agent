import Shell from "@/app/admin/shell";
import { api, fmtMoney } from "@/lib/api";
import { requireSession } from "@/lib/session";

export default async function Overview() {
  await requireSession();
  const o = await api("/v1/admin/overview");
  const cards = [
    ["users", o.users], ["items", o.items], ["spend today", `${fmtMoney(o.spend.today)} / ${fmtMoney(o.caps.global_daily)}`],
    ["spend this month", `${fmtMoney(o.spend.month)} / ${fmtMoney(o.caps.global_monthly)}`],
    ["jobs", Object.entries(o.jobs).map(([k, v]) => `${v} ${k}`).join(", ") || "none"],
    ["messages 24h", `${o.messages_24h.in ?? 0} in, ${o.messages_24h.out ?? 0} out`],
    ["storage", o.storage?.bytes != null ? `${(o.storage.bytes / 1e6).toFixed(1)} MB, ${o.storage.objects} objects` : (o.storage?.error ?? "?")],
  ];
  return (
    <Shell title="overview">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {cards.map(([k, v]) => <div key={String(k)} className="card"><div className="muted text-xs uppercase tracking-wide">{k}</div><div className="text-xl mt-1">{String(v)}</div></div>)}
      </div>
    </Shell>
  );
}
