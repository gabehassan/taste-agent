"use client";
import Link from "next/link";
import { motion } from "motion/react";

export const clean = (s: string) => (s || "").trim().replace(/^[“”"'‘’]+|[“”"'‘’]+$/g, "").trim();
export const host = (u?: string | null) => { try { return u ? new URL(u).hostname.replace(/^www\./, "") : ""; } catch { return ""; } };
export const favicon = (u?: string | null, size = 64) => { const h = host(u); return h ? `https://www.google.com/s2/favicons?domain=${h}&sz=${size}` : ""; };

const IMAGE_KINDS = new Set(["screenshot", "tiktok", "video", "youtube", "instagram", "film", "book"]);

export default function Block({ it, rel, index = 0 }: { it: any; rel: string; index?: number }) {
  const thumb = it.meta?.thumbnail || it.media_urls?.[0];
  const avatar = it.meta?.author_avatar;
  const quote = clean(it.snippets?.[0] || "");
  const isImage = !!thumb && IMAGE_KINDS.has(it.kind);
  const isText = !isImage && quote.length > 0;
  const who = it.kind === "tweet" && it.author ? it.author.split(" (")[0] : host(it.url) || it.source;
  return (
    <motion.div variants={{ hidden: { opacity: 0 }, show: { opacity: 1, transition: { duration: 0.35, delay: (index % 16) * 0.02 } } }} className="group">
      <Link href={`/items/${it.id}`} className="block">
        <div className="aspect-square relative overflow-hidden transition-colors duration-200" style={{ background: isImage ? "var(--paper-2)" : "var(--card)", border: "1px solid var(--line)", opacity: it.status === "archived" ? 0.45 : 1 }}
          onMouseEnter={undefined}>
          {isImage && <img src={thumb} alt="" className="absolute inset-0 w-full h-full object-cover" loading="lazy" />}
          {!isImage && (
            <div className="absolute inset-0 p-4 flex flex-col">
              {isText ? (
                <p className="u-quote overflow-hidden" style={{ display: "-webkit-box", WebkitLineClamp: 9, WebkitBoxOrient: "vertical", fontSize: quote.length > 240 ? 13 : quote.length > 120 ? 14 : 16 }}>{quote}</p>
              ) : (
                <div className="flex-1 flex flex-col">
                  {thumb && <img src={thumb} alt="" className="w-full h-[55%] object-cover mb-3" loading="lazy" />}
                  <div className="display text-[15px] leading-snug line-clamp-5">{it.title || it.url}</div>
                </div>
              )}
              <div className="mt-auto pt-3 flex items-center gap-2 min-w-0">
                {avatar ? <img src={avatar} alt="" className="w-5 h-5 rounded-full object-cover shrink-0" /> : favicon(it.url) ? <img src={favicon(it.url)} alt="" className="w-3.5 h-3.5 shrink-0" /> : null}
                <span className="mono u-faint truncate">{who}</span>
              </div>
            </div>
          )}
          {isImage && (avatar || favicon(it.url)) && <div className="absolute left-2 bottom-2 flex items-center gap-1.5 px-1.5 py-1" style={{ background: "var(--paper)" }}>{avatar ? <img src={avatar} alt="" className="w-4 h-4 rounded-full object-cover" /> : <img src={favicon(it.url)} alt="" className="w-3.5 h-3.5" />}<span className="mono" style={{ color: "var(--ink)" }}>{who}</span></div>}
          <div className="absolute inset-0 pointer-events-none transition-opacity duration-200 opacity-0 group-hover:opacity-100" style={{ boxShadow: "inset 0 0 0 1px var(--line-2)" }} />
        </div>
        <div className="mt-2 flex items-baseline gap-2 min-w-0">
          <div className="text-[13px] leading-snug truncate">{it.title || it.url}</div>
          <div className="mono u-faint ml-auto shrink-0">{rel}</div>
        </div>
        {(it.status === "read" || it.status === "pending" || it.read_minutes > 12) && <div className="mono u-faint">{it.status === "read" ? "finished" : it.status === "pending" ? "still reading it" : `${it.read_minutes} min`}</div>}
      </Link>
    </motion.div>
  );
}

export function Grid({ children }: { children: React.ReactNode }) {
  return <motion.div initial="hidden" animate="show" variants={{ hidden: {}, show: { transition: { staggerChildren: 0.015 } } }} className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-x-5 gap-y-8">{children}</motion.div>;
}
