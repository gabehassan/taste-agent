"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [["/", "index"], ["/items", "blocks"], ["/taste", "taste"], ["/memory", "memory"], ["/connections", "sources"], ["/settings", "settings"]];

export default function Nav({ name }: { name: string }) {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-20" style={{ background: "var(--paper)", borderBottom: "1px solid var(--line)" }}>
      <div className="mx-auto max-w-[1400px] px-6 h-12 flex items-center gap-8">
        <Link href="/" className="font-medium tracking-tight">taste</Link>
        <nav className="flex gap-5 text-sm">
          {NAV.map(([href, label]) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return <Link key={href} href={href} className="hover:opacity-100 transition-opacity" style={{ opacity: active ? 1 : 0.45, textDecoration: active ? "underline" : "none", textUnderlineOffset: 6 }}>{label}</Link>;
          })}
        </nav>
        <div className="ml-auto flex items-center gap-4 text-sm">
          <span className="u-muted">{name}</span>
          <form action="/api/logout" method="post"><button className="u-faint hover:underline">log out</button></form>
        </div>
      </div>
    </header>
  );
}
