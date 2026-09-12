"use client";
import { useActionState } from "react";
import Link from "next/link";
import { giveFeedback } from "@/app/user-actions";

export type DailyPick = { label: string; reason: string; item: {
  id: number; title: string; author?: string; kind: string; source?: string;
  summary?: string; why?: string; url?: string; read_minutes?: number;
  quote?: string; tags?: string[]; meta?: { thumbnail?: string };
} };

function Pick({ pick, index }: { pick: DailyPick; index: number }) {
  const [state, action, pending] = useActionState(giveFeedback, { message: "", error: false });
  const it = pick.item;
  const quote = (it.quote || "").trim().replace(/^[“”"'‘’]+|[“”"'‘’]+$/g, "");
  return <article className={`daily-pick pick-${index}`}>
    <div className="flex items-center justify-between mb-8"><span className="mono u-muted">0{index + 1} / {pick.label}</span><span className="pick-dot" /></div>
    {it.meta?.thumbnail && <div className="pick-image" style={{ backgroundImage: `url(${JSON.stringify(it.meta.thumbnail)})` }} />}
    <div className="mono u-muted mb-3">{it.kind}{it.read_minutes ? ` · ${it.read_minutes} min` : ""}</div>
    <Link href={`/items/${it.id}`} className="pick-title">{it.title}</Link>
    <p className="pick-excerpt">{quote ? `“${quote}”` : it.summary || "something you thought was worth keeping."}</p>
    <div className="mt-auto pt-6">
      <p className="text-xs u-muted mb-5 leading-relaxed">{it.why || pick.reason}</p>
      <Link href={`/items/${it.id}`} className="pick-open">spend a moment <span aria-hidden="true">↗</span></Link>
      <form action={action} className="pick-feedback">
        <input type="hidden" name="id" value={it.id} />
        <button name="action" value="finished" disabled={pending}>finished <span aria-hidden="true">✓</span></button>
        <button name="action" value="later" disabled={pending}>another day</button>
        <button name="action" value="not_for_me" disabled={pending} aria-label={`Not for me: ${it.title}`}>not for me</button>
      </form>
      {state.message && <p role={state.error ? "alert" : "status"} className="text-xs mt-3 u-muted">{state.message}</p>}
    </div>
  </article>;
}

export default function DailyPicks({ picks }: { picks: DailyPick[] }) {
  return <div className="daily-grid">{picks.map((p, i) => <Pick key={p.item.id} pick={p} index={i} />)}</div>;
}
