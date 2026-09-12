import UserShell, { me } from "../user-shell";
import { Fade } from "@/components/motion";
import { relTime, userApi } from "@/lib/user";
import { addConnection, removeConnection, syncConnection } from "../user-actions";

const COPY: Record<string, { blurb: string; placeholder: Record<string, string> }> = {
  letterboxd: { blurb: "diary and ratings. polled hourly from your public profile.", placeholder: { username: "letterboxd username" } },
  goodreads: { blurb: "shelves and stars. the number from your profile url.", placeholder: { user_id: "goodreads user id" } },
  substack: { blurb: "the substacks you actually read. new posts get read and filed quietly, no texts.", placeholder: { url: "name, name.substack.com, or a url" } },
  rss: { blurb: "anything with a feed.", placeholder: { url: "https://…/feed" } },
};
const SOON = ["TikTok favorites", "Instagram saved", "X bookmarks", "Spotify"];

function Row({ c, label }: { c: any; label: string }) {
  return (
    <div className="hair py-3 flex items-center gap-4 text-sm">
      <div className="w-28 shrink-0">{label}</div>
      <div className="flex-1 min-w-0 truncate">{c.config.title || Object.values(c.config).filter((v: any) => typeof v === "string").join(" ")}</div>
      <div className="mono u-faint shrink-0">{c.last_error ? <span style={{ color: "var(--ink)" }}>trouble</span> : c.last_synced_at ? `synced ${relTime(c.last_synced_at)}` : "syncing…"}</div>
      <form action={syncConnection}><input type="hidden" name="cid" value={c.id} /><button className="mono u-faint hover:underline">sync</button></form>
      <form action={removeConnection}><input type="hidden" name="cid" value={c.id} /><button className="mono u-faint hover:underline">remove</button></form>
    </div>
  );
}

export default async function Connections() {
  const m = await me();
  const { connections, types } = await userApi("/v1/connections");
  const order = ["substack", "letterboxd", "goodreads", "rss"];
  return (
    <UserShell name={m.user.name || ""}>
      <Fade>
        <div className="max-w-3xl">
          <h1 className="display text-[28px] mb-2">sources</h1>
          <p className="u-muted mb-12">the more of your taste I can see, the less I guess. all read-only. pull any of it whenever.</p>
          {order.map(type => {
            const t = types[type]; if (!t) return null;
            const mine = connections.filter((c: any) => c.type === type);
            const copy = COPY[type];
            const canAdd = t.multi || mine.length === 0;
            return (
              <section key={type} className="mb-12">
                <div className="flex items-baseline gap-4 mb-1"><h2 className="display text-[20px]">{type === "substack" ? "substacks you read" : t.label}</h2><span className="mono u-faint">{mine.length || ""}</span></div>
                <p className="u-muted text-sm mb-4">{copy.blurb}</p>
                {mine.map((c: any) => <Row key={c.id} c={c} label={t.label} />)}
                {mine.some((c: any) => c.last_error) && <div className="mono u-faint mt-1">{mine.find((c: any) => c.last_error).last_error}</div>}
                {canAdd && (
                  <form action={addConnection} className="flex gap-2 mt-3 max-w-lg">
                    <input type="hidden" name="type" value={type} />
                    {t.config.map((k: string) => <input key={k} name={`cfg_${k}`} placeholder={copy.placeholder[k] || k} required className="u-input" style={{ padding: "8px 10px", fontSize: 13 }} />)}
                    <button className="u-btn soft">add</button>
                  </form>
                )}
              </section>
            );
          })}
          <section className="hair pt-4">
            <div className="mono u-faint mb-2">soon</div>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm u-muted">{SOON.map(n => <span key={n}>{n}</span>)}</div>
          </section>
        </div>
      </Fade>
    </UserShell>
  );
}
