import UserShell, { me } from "../user-shell";
import { Fade, Stagger } from "@/components/motion";
import { relTime, userApi } from "@/lib/user";
import { addConnection, removeConnection, syncConnection } from "../user-actions";

const COPY: Record<string, { blurb: string; hint: string; placeholder: Record<string, string> }> = {
  letterboxd: { blurb: "your diary and ratings, so I know what you actually loved on screen.", hint: "public profile, polled hourly", placeholder: { username: "your letterboxd username" } },
  goodreads: { blurb: "shelves and stars. the read shelf is the most honest signal you have.", hint: "the number in your profile URL", placeholder: { user_id: "e.g. 12345678" } },
  rss: { blurb: "a newsletter, a blog, anything with a feed. new posts get read and filed, no texts.", hint: "any feed url", placeholder: { url: "https://…/feed" } },
};
const SOON = [["TikTok favorites", "upload your data export"], ["Instagram saved", "upload your data export"], ["X bookmarks", "official API, coming"], ["Spotify", "liked songs and podcasts"]];

export default async function Connections() {
  const m = await me();
  const { connections, types } = await userApi("/v1/connections");
  return (
    <UserShell name={m.user.name || ""}>
      <Fade><h1 className="display text-4xl pt-6 mb-2">connections</h1></Fade>
      <Fade delay={0.05}><p className="u-muted mb-8 max-w-xl">the more of your taste I can see, the less I guess. everything here is read-only and you can pull it any time.</p></Fade>
      <Stagger className="grid md:grid-cols-3 gap-4">
        {Object.entries(types).map(([type, t]: any) => {
          const c = connections.find((x: any) => x.type === type);
          const copy = COPY[type];
          return (
            <Fade key={type} className="u-card p-5 flex flex-col gap-3">
              <div className="flex items-center justify-between"><div className="display text-2xl">{t.label}</div>{c && <span className="u-chip" style={{ background: c.last_error ? "var(--accent-soft)" : "var(--paper-2)" }}>{c.last_error ? "trouble" : "connected"}</span>}</div>
              <p className="u-muted text-sm">{copy?.blurb}</p>
              {c ? (
                <div className="text-sm">
                  <div className="u-faint">{Object.values(c.config).join(" ")} · {c.last_synced_at ? `synced ${relTime(c.last_synced_at)}` : "syncing…"}</div>
                  {c.last_error && <div className="text-xs mt-1" style={{ color: "var(--accent)" }}>{c.last_error}</div>}
                  <div className="flex gap-2 mt-3">
                    <form action={syncConnection}><input type="hidden" name="cid" value={c.id} /><button className="u-btn soft" style={{ padding: "6px 12px" }}>sync now</button></form>
                    <form action={removeConnection}><input type="hidden" name="cid" value={c.id} /><button className="u-btn soft" style={{ padding: "6px 12px" }}>remove</button></form>
                  </div>
                </div>
              ) : (
                <form action={addConnection} className="flex flex-col gap-2 mt-auto">
                  <input type="hidden" name="type" value={type} />
                  {t.config.map((k: string) => <input key={k} name={`cfg_${k}`} placeholder={copy?.placeholder[k] || k} required className="u-input" style={{ padding: "8px 12px", fontSize: 14 }} />)}
                  <button className="u-btn">connect</button>
                  <span className="u-faint text-xs">{copy?.hint}</span>
                </form>
              )}
            </Fade>
          );
        })}
        {SOON.map(([n, h]) => <Fade key={n} className="u-card p-5 opacity-70"><div className="display text-2xl">{n}</div><p className="u-faint text-sm mt-2">{h}</p><span className="u-chip mt-3 inline-block">soon</span></Fade>)}
      </Stagger>
    </UserShell>
  );
}
