"use client";
import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
const ease = [0.25, 0.1, 0.25, 1] as const;

const TITLES: Record<string, string> = { stranger: "it barely knows you yet", acquaintance: "it's starting to get you", friend: "it knows you", "close friend": "it knows you well", "knows you": "it knows you better than most" };

export default function Growth({ p }: { p: any }) {
  const [open, setOpen] = useState(false);
  const undone = p.quests.filter((q: any) => !q.done);
  const next = undone[0];
  const pctLevel = p.next ? Math.min(100, Math.round((p.items / p.next.at) * 100)) : 100;
  return (
    <section className="mb-12">
      <button onClick={() => setOpen(!open)} className="text-left w-full group">
        <div className="flex items-baseline gap-4 flex-wrap">
          <span className="text-[15px]">{TITLES[p.title] || p.title}.</span>
          {next && <span className="u-muted text-[15px]">next: {next.label}.</span>}
          <span className="mono u-faint ml-auto group-hover:underline">{open ? "less" : `${p.done} of ${p.total}`}</span>
        </div>
        <div className="h-px mt-3 relative max-w-md" style={{ background: "var(--line)" }}>
          <motion.div className="absolute left-0 top-0 h-px" style={{ background: "var(--ink)" }} initial={{ width: 0 }} animate={{ width: `${Math.max(2, pctLevel)}%` }} transition={{ duration: 0.9, ease }} />
        </div>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3, ease }} className="overflow-hidden">
            <div className="grid md:grid-cols-2 gap-x-12 pt-5 max-w-3xl">
              {p.quests.map((q: any) => (
                <div key={q.id} className="hair py-2.5 text-sm flex items-baseline gap-3" style={{ opacity: q.done ? 0.45 : 1 }}>
                  <span className="mono u-faint w-9 shrink-0">{q.done ? "done" : `${q.progress}/${q.of}`}</span>
                  <span>{q.label}<span className="u-faint"> · {q.unlocks}</span></span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
