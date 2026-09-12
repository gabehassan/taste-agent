import Shell from "@/app/admin/shell";
import { api } from "@/lib/api";
import { requireSession } from "@/lib/session";
import { saveSettings } from "@/app/admin/actions";

const GROUPS: Record<string, string[]> = {
  "spending": ["global_daily_cap_usd", "global_monthly_cap_usd", "default_user_daily_cap_usd"],
  "surfacing defaults": ["surfaces_per_day", "wake_start", "wake_end", "min_gap_minutes", "observation_chance", "profile_refresh_every", "profile_max_age_hours"],
  "rate limits": ["rate_ip_per_min", "rate_key_per_hour", "rate_inbound_per_hour", "rate_inbound_per_day", "rate_ingest_per_day", "rate_chat_per_day", "rate_outbound_per_hour"],
};

export default async function Settings({ searchParams }: { searchParams: Promise<{ e?: string }> }) {
  await requireSession();
  const { e } = await searchParams;
  const { settings } = await api("/v1/admin/settings");
  return (
    <Shell title="settings">
      {e === "json" && <div className="text-red-400 mb-3">model_prices was not valid JSON</div>}
      <form action={saveSettings} className="flex flex-col gap-6">
        {Object.entries(GROUPS).map(([g, keys]) => (
          <div key={g} className="card"><div className="font-medium mb-3">{g}</div>
            <div className="grid md:grid-cols-4 gap-3">{keys.map(k => <label key={k} className="text-xs muted flex flex-col gap-1">{k}<input name={k} type="number" step="any" defaultValue={settings[k]} /></label>)}</div>
          </div>
        ))}
        <div className="card"><div className="font-medium mb-1">model prices</div><div className="muted text-xs mb-2">USD per 1M tokens (in / out / cached_in) or per_minute for audio. Used to compute spend against the caps.</div>
          <textarea name="model_prices" rows={8} className="w-full font-mono text-xs" defaultValue={JSON.stringify(settings.model_prices, null, 2)} /></div>
        <div><button>save</button></div>
      </form>
    </Shell>
  );
}
