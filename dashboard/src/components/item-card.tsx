"use client";
import Link from "next/link";
import { Item } from "./motion";

const KIND_LABEL: Record<string, string> = { article: "essay", essay: "essay", tweet: "tweet", thread: "thread", reddit: "reddit", tiktok: "tiktok", video: "video", youtube: "video", podcast: "podcast", book: "book", film: "film", paper: "paper", screenshot: "screenshot", note: "note", link: "link" };

export default function ItemCard({ it, rel }: { it: any; rel: string }) {
  const thumb = it.meta?.thumbnail || it.media_urls?.[0];
  const quote = it.snippets?.[0];
  return (
    <Item className="break-inside-avoid mb-4">
      <Link href={`/items/${it.id}`} className="u-card block overflow-hidden" style={{ opacity: it.status === "archived" ? 0.55 : 1 }}>
        {thumb && <img src={thumb} alt="" className="w-full object-cover" style={{ maxHeight: 260 }} loading="lazy" />}
        <div className="p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="u-kicker">{KIND_LABEL[it.kind] || it.kind}</span>
            <span className="u-faint text-xs">· {it.source}</span>
            {it.status === "read" && <span className="u-chip ml-auto">read</span>}
            {it.status === "pending" && <span className="u-chip ml-auto">reading…</span>}
          </div>
          <div className="display text-lg leading-snug">{it.title || it.url}</div>
          {quote && it.kind !== "tweet" && <p className="u-quote mt-2 u-muted line-clamp-4">“{quote}”</p>}
          {it.kind === "tweet" && it.summary && <p className="mt-2 text-sm u-muted line-clamp-4">{it.summary}</p>}
          <div className="mt-3 flex flex-wrap gap-1 items-center">
            {(it.tags || []).slice(0, 3).map((t: string) => <span key={t} className="u-chip">{t}</span>)}
            <span className="u-faint text-xs ml-auto">{rel}</span>
          </div>
        </div>
      </Link>
    </Item>
  );
}
