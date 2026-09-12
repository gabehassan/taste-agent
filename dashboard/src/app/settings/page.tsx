import UserShell, { me } from "../user-shell";
import { Fade } from "@/components/motion";
import { saveSettings } from "../user-actions";

export default async function Settings() {
  const m = await me();
  const u = m.user; const s = u.settings || {};
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const fmt = (h: number) => `${((h + 11) % 12) + 1}${h < 12 ? "am" : "pm"}`;
  return (
    <UserShell name={u.name || ""}>
      <Fade><h1 className="display text-4xl pt-6 mb-8">settings</h1></Fade>
      <Fade delay={0.1}>
        <form action={saveSettings} className="u-card p-6 flex flex-col gap-6 max-w-xl">
          <label className="flex flex-col gap-2"><span className="u-kicker">what should I call you</span><input name="name" defaultValue={u.name || ""} className="u-input" /></label>
          <div className="flex flex-col gap-2"><span className="u-kicker">how many times a day should I text you something</span>
            <div className="flex gap-2 flex-wrap">{[0, 1, 2, 3, 4, 5].map(n => <label key={n} className="u-chip cursor-pointer" style={{ padding: "8px 14px" }}><input type="radio" name="surfaces_per_day" value={n} defaultChecked={(s.surfaces_per_day ?? 3) === n} className="mr-2" />{n === 0 ? "never" : n}</label>)}</div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <label className="flex flex-col gap-2"><span className="u-kicker">not before</span><select name="wake_start" defaultValue={s.wake_start ?? 10} className="u-input">{hours.map(h => <option key={h} value={h}>{fmt(h)}</option>)}</select></label>
            <label className="flex flex-col gap-2"><span className="u-kicker">not after</span><select name="wake_end" defaultValue={s.wake_end ?? 22} className="u-input">{hours.slice(1).concat([24]).map(h => <option key={h} value={h}>{h === 24 ? "midnight" : fmt(h)}</option>)}</select></label>
          </div>
          <label className="flex flex-col gap-2"><span className="u-kicker">time zone</span><input name="tz" defaultValue={u.tz} className="u-input" /></label>
          <label className="flex items-center gap-3"><input type="checkbox" name="paused" defaultChecked={!!s.paused} className="w-5 h-5" /><span>pause the drops for now (you can still text me)</span></label>
          <div><button className="u-btn">save</button></div>
        </form>
      </Fade>
      <Fade delay={0.2} className="u-muted text-sm mt-8 max-w-xl">your number is the login. text me <b>login</b> any time for a fresh link. spent today: ${Number(m.spend_today).toFixed(2)}.</Fade>
    </UserShell>
  );
}
