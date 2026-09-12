"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Fade, Stagger } from "./motion";

const rel = (s: string) => { const d = (Date.now() - new Date(s).getTime()) / 1000; return d < 3600 ? `${Math.max(1, Math.floor(d / 60))}m ago` : d < 86400 ? `${Math.floor(d / 3600)}h ago` : `${Math.floor(d / 86400)}d ago`; };
const pct = (x: number | undefined) => `${Math.round((x ?? 0) * 100)}%`;

function Meter({ label, value, hint }: { label: string; value: number; hint: string }) {
  return (
    <div>
      <div className="flex justify-between text-sm"><span>{label}</span><span className="u-faint">{pct(value)}</span></div>
      <div className="h-1.5 rounded-full mt-1" style={{ background: "var(--paper-2)" }}>
        <motion.div className="h-1.5 rounded-full" style={{ background: "var(--accent)" }} initial={{ width: 0 }} animate={{ width: pct(value) }} transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} />
      </div>
      <div className="u-faint text-xs mt-1">{hint}</div>
    </div>
  );
}

function Prompt({ name, about, text }: { name: string; about: string; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="u-card p-4">
      <button onClick={() => setOpen(!open)} className="w-full text-left flex items-baseline gap-3">
        <span className="display text-xl">{name}</span><span className="u-faint text-xs ml-auto">{open ? "hide" : "show prompt"}</span>
      </button>
      <p className="u-muted text-sm mt-1 whitespace-pre-wrap">{about}</p>
      <AnimatePresence initial={false}>
        {open && (
          <motion.pre initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.35 }}
            className="mt-3 text-xs whitespace-pre-wrap overflow-hidden rounded-xl p-3" style={{ background: "var(--paper-2)", fontFamily: "ui-monospace, monospace" }}>{text}</motion.pre>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function MemoryView({ m, admin = false }: { m: any; admin?: boolean }) {
  const v = m.voice.stats || {};
  const name = (m.user.name || "them").split(" ")[0];
  return (
    <div className="grid md:grid-cols-[1fr_340px] gap-10 pt-6">
      <div className="flex flex-col gap-8">
        <section>
          <Fade><div className="u-kicker mb-2">{admin ? `how the agent talks to ${name}` : "why I talk to you the way I do"}</div></Fade>
          <Fade delay={0.05}><p className="display text-3xl leading-tight">“{m.voice.sentence}”</p></Fade>
          <Fade delay={0.1} className="u-muted text-sm mt-2">learned from the last {v.n ?? 0} texts {admin ? "they" : "you"} sent. it updates every message.</Fade>
          <Stagger className="u-card p-5 mt-4 grid md:grid-cols-2 gap-5">
            <Fade><Meter label="lowercase" value={v.lowercase} hint="share of letters typed lowercase" /></Fade>
            <Fade><Meter label="emoji" value={v.emoji} hint="share of texts with an emoji" /></Fade>
            <Fade><Meter label="energy" value={v.exclaim} hint="exclamation marks, lol, omg" /></Fade>
            <Fade><div><div className="flex justify-between text-sm"><span>length</span><span className="u-faint">{Math.round(v.avg_len ?? 0)} chars</span></div><div className="u-faint text-xs mt-1">average text length, rolling</div></div></Fade>
          </Stagger>
        </section>

        <section>
          <Fade><div className="u-kicker mb-3">what it remembers from the last few days</div></Fade>
          <div className="u-card p-4 flex flex-col gap-2 max-h-[28rem] overflow-auto">
            {m.chat_memory.length === 0 && <div className="u-faint text-sm">no conversation yet, just links.</div>}
            {m.chat_memory.map((t: any, i: number) => (
              <div key={i} className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${t.role === "user" ? "self-end" : "self-start"}`} style={{ background: t.role === "user" ? "var(--accent)" : "var(--paper-2)", color: t.role === "user" ? "#fff" : "var(--ink)" }}>{t.content}</div>
            ))}
          </div>
          <div className="u-faint text-xs mt-2">only the last 12 turns within 12 hours are shown to the model each time. older conversation is forgotten on purpose; the taste profile is the long-term memory.</div>
        </section>

        <section>
          <Fade><div className="u-kicker mb-3">the prompts, as the model sees them for {admin ? name : "you"}</div></Fade>
          <div className="flex flex-col gap-3">
            <Prompt name="voice" about={m.prompts.about.voice} text={m.voice.rendered} />
            <Prompt name="digest" about={m.prompts.about.digest} text={m.prompts.digest} />
            <Prompt name="chat" about={m.prompts.about.chat} text={m.prompts.chat} />
            <Prompt name="profile" about={m.prompts.about.profile} text={m.prompts.profile} />
          </div>
        </section>
      </div>

      <aside className="flex flex-col gap-6">
        <Fade delay={0.15}>
          <div className="u-kicker mb-2">long-term memory</div>
          <div className="u-card p-4 text-sm">
            {m.profile ? (<>
              <p className="u-quote">{m.profile.one_liner}</p>
              <div className="u-faint text-xs mt-2">profile v{m.profile_history.length}, from {m.profile.item_count} things, {rel(m.profile.created_at)}. {m.schedule.items_since_profile} new since.</div>
            </>) : <span className="u-faint">no profile yet</span>}
          </div>
        </Fade>
        <Fade delay={0.2}>
          <div className="u-kicker mb-2">what {admin ? name : "you"} keep{admin ? "s" : ""} reaching for</div>
          <div className="flex flex-wrap gap-1">{m.tags.map((t: any) => <span key={t.tag} className="u-chip" style={{ fontSize: 12 + Math.min(t.n, 6) }}>{t.tag} <span className="u-faint ml-1">{t.n}</span></span>)}</div>
        </Fade>
        {m.reactions.length > 0 && <Fade delay={0.25}>
          <div className="u-kicker mb-2">reactions it noticed</div>
          <div className="u-card p-4 text-sm flex flex-col gap-1">{m.reactions.map((r: any) => <div key={r.item_id}><span className="u-faint">{r.reactions.join(" ")}</span> {r.title}</div>)}</div>
        </Fade>}
        <Fade delay={0.3}>
          <div className="u-kicker mb-2">today</div>
          <div className="u-card p-4 text-sm flex flex-col gap-1">
            <div>drops: {(m.schedule.plan?.slots || []).map((s: any) => <span key={s.at} className="u-chip mr-1" style={{ opacity: s.done ? 0.5 : 1 }}>{s.at.slice(11, 16)}{s.done ? " ✓" : ""}</span>)}{!(m.schedule.plan?.slots || []).length && <span className="u-faint">none planned</span>}</div>
            <div className="u-faint text-xs">{m.schedule.settings?.paused ? "paused" : `${m.schedule.settings?.surfaces_per_day ?? 3} per day, ${m.schedule.settings?.wake_start ?? 10}:00 to ${m.schedule.settings?.wake_end ?? 22}:00`} · spent ${Number(m.spend.today).toFixed(2)} today, ${Number(m.spend.month).toFixed(2)} this month</div>
          </div>
        </Fade>
        <Fade delay={0.35}>
          <div className="u-kicker mb-2">last things it texted</div>
          <div className="flex flex-col gap-2">{m.recent_texts.filter((t: any) => t.direction === "out").slice(0, 6).map((t: any) => <div key={t.id} className="u-card p-3 text-xs"><span className="u-faint">{t.kind === "reaction" ? `${t.meta?.emoji || "reaction"} ` : ""}{t.status} · {rel(t.created_at)}</span><div className="mt-1 line-clamp-3">{t.text}</div></div>)}</div>
        </Fade>
      </aside>
    </div>
  );
}
