import UserShell, { me } from "../../user-shell";
import { Fade } from "@/components/motion";
import { clean, favicon, host } from "@/components/block";
import type { Item } from "@/lib/types";
import { relTime, userApi } from "@/lib/user";
import { onboardingConfig, messageLink } from "@/lib/onboarding";
import { setStatus } from "../../user-actions";

export default async function ItemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const m = await me();
  const it = await userApi<Item>(`/v1/items/${id}`);
  const contact = await onboardingConfig();
  const thumb = it.meta?.thumbnail || it.media_urls?.[0];
  return (
    <UserShell name={m.user.name || ""}>
      <Fade>
        <article className="grid md:grid-cols-[minmax(0,720px)_260px] gap-16">
          <div>
            <div className="mono u-faint mb-4 flex items-center gap-2">
              {it.meta?.author_avatar ? <img src={it.meta.author_avatar} alt="" className="w-4 h-4 rounded-full object-cover" /> : favicon(it.url) ? <img src={favicon(it.url)} alt="" className="w-3.5 h-3.5" /> : null}
              <span>{it.kind} · {host(it.url) || it.source} · {relTime(it.created_at)}</span>
            </div>
            <h1 className="display text-[28px] md:text-[36px] mb-2">{it.title}</h1>
            {it.author && <div className="u-muted mb-8">{it.author}</div>}
            {thumb && <img src={thumb} alt="" className="w-full max-h-[480px] object-cover mb-10" style={{ border: "1px solid var(--line)" }} />}
            <p className="text-[16px] leading-relaxed mb-10 max-w-[620px]">{it.summary}</p>
            <div className="flex flex-col gap-6 max-w-[620px]">
              {(it.snippets || []).map((s, i) => <p key={i} className="u-quote pl-4" style={{ borderLeft: "1px solid var(--line-2)" }}>{clean(s)}</p>)}
            </div>
            {it.why && <p className="u-muted mt-10 max-w-[620px]">{it.why}</p>}
            {it.transcript && <details className="mt-10"><summary className="mono u-faint cursor-pointer">transcript</summary><p className="mt-3 text-[13px] leading-relaxed whitespace-pre-wrap u-muted max-w-[620px]">{it.transcript}</p></details>}
            {it.raw_text && it.kind !== "screenshot" && <details className="mt-4"><summary className="mono u-faint cursor-pointer">full text</summary><p className="mt-3 text-[13px] leading-relaxed whitespace-pre-wrap u-muted max-w-[620px]">{it.raw_text.slice(0, 30000)}</p></details>}
          </div>
          <aside className="text-sm flex flex-col gap-6 md:pt-10">
            {contact?.phone && <a href={messageLink(contact.phone, `Let’s talk about saved item #${it.id}: ${it.title}`)} className="u-btn text-center">talk about this with taste ↗</a>}
            <p className="text-xs u-muted leading-relaxed">what stayed with you? one thought is enough. taste can pick up the conversation from here.</p>
            {it.url && <a href={it.url} target="_blank" className="u-btn text-center">open original ↗</a>}
            <div className="mono u-faint flex flex-col gap-1">
              <span>{it.read_minutes} min read</span><span>surfaced {it.surfaced_count}×</span>
              {!!it.meta?.reactions?.length && <span>you reacted {it.meta.reactions.join(" ")}</span>}
            </div>
            {it.note && <div><div className="mono u-faint mb-1">your note</div><div>{it.note}</div></div>}
            <div className="flex flex-wrap gap-1">{(it.tags || []).map(t => <a key={t} href={`/items?q=${encodeURIComponent(t)}`} className="u-chip hover:border-current">{t}</a>)}</div>
            <div className="flex gap-2 flex-wrap hair pt-4">
              {["unread", "read", "archived"].map(s => <form key={s} action={setStatus}><input type="hidden" name="id" value={it.id} /><input type="hidden" name="status" value={s} /><button className={`u-btn ${s === it.status ? "" : "soft"}`} style={{ padding: "6px 10px", fontSize: 12 }}>{s}</button></form>)}
            </div>
          </aside>
        </article>
      </Fade>
    </UserShell>
  );
}
