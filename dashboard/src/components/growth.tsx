"use client";
import { motion } from "motion/react";
const ease = [0.25, 0.1, 0.25, 1] as const;

export default function Growth({ p }: { p: any }) {
  const pctLevel = p.next ? Math.min(100, Math.round((p.items / p.next.at) * 100)) : 100;
  const undone = p.quests.filter((q: any) => !q.done);
  const done = p.quests.filter((q: any) => q.done);
  return (
    <section className="hair pt-3 mb-12">
      <div className="grid md:grid-cols-[280px_1fr] gap-x-16 gap-y-6">
        <div>
          <div className="mono u-faint mb-3">how well it knows you</div>
          <div className="display text-[22px]">{p.title}</div>
          <div className="h-px mt-3 relative" style={{ background: "var(--line)" }}>
            <motion.div className="absolute left-0 top-0 h-px" style={{ background: "var(--ink)" }} initial={{ width: 0 }} animate={{ width: `${Math.max(2, pctLevel)}%` }} transition={{ duration: 0.9, ease }} />
          </div>
          <div className="mono u-faint mt-2">{p.next ? `${p.items} of ${p.next.at} blocks until "${p.next.title}"` : "as close as it gets"} · {p.done}/{p.total} done</div>
        </div>
        <div className="grid md:grid-cols-2 gap-x-10">
          <div>
            <div className="mono u-faint mb-2">next</div>
            {undone.slice(0, 4).map((q: any, i: number) => (
              <motion.div key={q.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.05, duration: 0.3 }} className="hair py-2.5 text-sm">
                <div className="flex items-baseline gap-3"><span className="mono u-faint w-8 shrink-0">{q.progress}/{q.of}</span><span>{q.label}</span></div>
                <div className="mono u-faint ml-11 mt-0.5">unlocks {q.unlocks}</div>
              </motion.div>
            ))}
            {undone.length === 0 && <div className="u-muted text-sm">nothing left. it knows you.</div>}
          </div>
          <div>
            <div className="mono u-faint mb-2">done</div>
            {done.length === 0 && <div className="u-muted text-sm hair py-2.5">nothing yet</div>}
            {done.map((q: any) => <div key={q.id} className="hair py-2.5 text-sm u-muted flex items-baseline gap-3"><span className="mono w-8 shrink-0">✓</span><span className="line-through decoration-1">{q.label}</span></div>)}
          </div>
        </div>
      </div>
    </section>
  );
}
