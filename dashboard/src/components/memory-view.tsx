"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import type { MemorySnapshot } from "@/lib/types";

const rel = (s: string) => { const d = (Date.now() - new Date(s).getTime()) / 1000; return d < 60 ? "now" : d < 3600 ? `${Math.floor(d / 60)}m` : d < 86400 ? `${Math.floor(d / 3600)}h` : `${Math.floor(d / 86400)}d`; };
const pct = (x: number | undefined) => Math.round((x ?? 0) * 100);
const ease = [0.25, 0.1, 0.25, 1] as const;

function Meter({ label, value, note }: { label: string; value: number; note: string }) {
  return (
    <div className="hair pt-3">
      <div className="flex items-baseline justify-between"><span className="text-sm">{label}</span><span className="mono u-faint">{value}</span></div>
      <div className="h-px mt-3 relative" style={{ background: "var(--line)" }}>
        <motion.div className="absolute left-0 top-0 h-px" style={{ background: "var(--ink)" }} initial={{ width: 0 }} animate={{ width: `${Math.max(2, value)}%` }} transition={{ duration: 0.8, ease }} />
      </div>
      <div className="mono u-faint mt-2">{note}</div>
    </div>
  );
}

function Bubble({ role, text }: { role: string; text: string }) {
  const me = role === "user";
  return (
    <div className={`flex ${me ? "justify-end" : "justify-start"}`}>
      <div className="max-w-[78%] px-3.5 py-2 text-[15px] leading-snug whitespace-pre-wrap" style={{
        background: me ? "#0a84ff" : "var(--paper-2)", color: me ? "#fff" : "var(--ink)",
        borderRadius: 18, borderBottomRightRadius: me ? 4 : 18, borderBottomLeftRadius: me ? 18 : 4,
      }}>{text}</div>
    </div>
  );
}

function Prompt({ name, about, text }: { name: string; about: string; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="hair py-4">
      <button onClick={() => setOpen(!open)} className="w-full text-left flex items-baseline gap-4 group">
        <span className="text-sm w-20 shrink-0">{name}</span>
        <span className="u-muted text-sm flex-1 line-clamp-2 group-hover:line-clamp-none">{about}</span>
        <span className="mono u-faint shrink-0">{open ? "close" : "read"}</span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3, ease }} className="overflow-hidden">
            <pre className="mono mt-4 p-4 whitespace-pre-wrap leading-relaxed" style={{ background: "var(--paper-2)", fontSize: 12 }}>{text}</pre>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function MemoryView({ m, admin = false }: { m: MemorySnapshot; admin?: boolean }) {
  const v = m.voice.stats || {};
  const name = (m.user.name || "them").split(" ")[0];
  const you = admin ? name : "you";
  const outs = m.recent_texts.filter(t => t.direction === "out" && t.text);
  const slots = m.schedule.plan?.slots || [];
  return (
    <div className="grid lg:grid-cols-[minmax(0,1fr)_360px] gap-x-20 gap-y-14">
      {/* left */}
      <div className="flex flex-col gap-16">
        <section>
          <div className="mono u-faint mb-6">how it talks to {you}</div>
          <motion.p initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease }} className="display text-[26px] md:text-[32px] max-w-2xl">
            {m.voice.sentence}.
          </motion.p>
          <p className="u-muted mt-4 max-w-xl text-sm">this sentence is pasted into every prompt. it is rebuilt from the last {v.n ?? 0} texts {you} sent, so it drifts as {you} do{admin ? "es" : ""}.</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-x-8 mt-8">
            <Meter label="lowercase" value={pct(v.lowercase)} note="share of letters typed lowercase" />
            <Meter label="emoji" value={pct(v.emoji)} note="texts with an emoji" />
            <Meter label="energy" value={pct(v.exclaim)} note="exclamation marks, lol, omg" />
            <Meter label="length" value={Math.min(100, Math.round((v.avg_len ?? 0) / 2))} note={`${Math.round(v.avg_len ?? 0)} characters on average`} />
          </div>
        </section>

        <section>
          <div className="flex items-baseline justify-between mb-6"><div className="mono u-faint">short-term memory</div><div className="mono u-faint">last 12 turns · 12 hours</div></div>
          {m.chat_memory.length === 0 ? (
            <p className="u-muted text-sm">no conversation in memory. links and commands don&apos;t count; only back-and-forth does.</p>
          ) : (
            <div className="flex flex-col gap-1.5 max-w-xl">
              {m.chat_memory.map((t, i) => (
                <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, delay: i * 0.03, ease }}><Bubble role={t.role} text={t.content} /></motion.div>
              ))}
            </div>
          )}
          <p className="mono u-faint mt-4">older conversation is forgotten on purpose. the taste profile is the long-term memory.</p>
        </section>

        <section>
          <div className="mono u-faint mb-2">the prompts, exactly as the model sees them for {you}</div>
          <div>
            <Prompt name="voice" about={m.prompts.about.voice} text={m.voice.rendered} />
            <Prompt name="digest" about={m.prompts.about.digest} text={m.prompts.digest} />
            <Prompt name="chat" about={m.prompts.about.chat} text={m.prompts.chat} />
            <Prompt name="profile" about={m.prompts.about.profile} text={m.prompts.profile} />
          </div>
        </section>
      </div>

      {/* right: a quiet feed */}
      <aside className="flex flex-col gap-12 lg:pt-1">
        <section>
          <div className="mono u-faint mb-3">long-term memory</div>
          {m.profile ? (
            <div>
              <p className="text-[16px] leading-snug">{m.profile.one_liner}</p>
              <div className="mono u-faint mt-2">profile v{m.profile_history.length} · {m.profile.item_count} blocks · {rel(m.profile.created_at)} ago · {m.schedule.items_since_profile} new since</div>
            </div>
          ) : <p className="u-muted text-sm">nothing written yet. it starts after a few real saves.</p>}
        </section>

        <section>
          <div className="mono u-faint mb-3">what {you} keep{admin ? "s" : ""} reaching for</div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {m.tags.length === 0 && <span className="u-muted">nothing yet</span>}
            {m.tags.map(t => <span key={t.tag}>{t.tag}<span className="mono u-faint ml-1">{t.n}</span></span>)}
          </div>
        </section>

        {m.reactions.length > 0 && (
          <section>
            <div className="mono u-faint mb-3">reactions it noticed</div>
            <div className="flex flex-col gap-1 text-sm">{m.reactions.map(r => <div key={r.item_id} className="truncate"><span className="u-faint mr-2">{r.reactions.join(" ")}</span>{r.title}</div>)}</div>
          </section>
        )}

        <section>
          <div className="mono u-faint mb-3">today</div>
          <div className="text-sm">
            {slots.length === 0 ? <span className="u-muted">no drops planned</span> : slots.map(s => <span key={s.at} className="mr-3" style={{ opacity: s.done ? 0.4 : 1 }}>{s.at.slice(11, 16)}{s.done ? " ✓" : ""}</span>)}
          </div>
          <div className="mono u-faint mt-2">{m.schedule.settings?.paused ? "paused" : `${m.schedule.settings?.surfaces_per_day ?? 3} a day, ${m.schedule.settings?.wake_start ?? 10}:00 to ${m.schedule.settings?.wake_end ?? 22}:00`} · ${Number(m.spend.today).toFixed(2)} today · ${Number(m.spend.month).toFixed(2)} this month</div>
        </section>

        <section>
          <div className="mono u-faint mb-3">sent</div>
          <div className="flex flex-col">
            {outs.slice(0, 8).map(t => (
              <div key={t.id} className="hair py-3">
                <div className="text-sm leading-snug line-clamp-3">{t.text}</div>
                <div className="mono u-faint mt-1">{t.status} · {rel(t.created_at)} ago</div>
              </div>
            ))}
            {outs.length === 0 && <span className="u-muted text-sm">nothing sent yet</span>}
          </div>
        </section>
      </aside>
    </div>
  );
}
