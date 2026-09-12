"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import TasteMark from "./taste-mark";

const NAV = [["/", "today"], ["/items", "collection"], ["/taste", "your taste"], ["/memory", "memory"], ["/connections", "sources"]];

export default function Nav({ name }: { name: string }) {
  const path = usePathname();
  return <header className="taste-nav">
    <div className="taste-nav-inner">
      <Link href="/" className="taste-wordmark"><TasteMark small />taste</Link>
      <nav aria-label="Main navigation" className="taste-nav-links">
        {NAV.map(([href, label]) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          return <Link key={href} href={href} aria-current={active ? "page" : undefined}>{label}</Link>;
        })}
      </nav>
      <Link href="/settings" className="taste-account" aria-label="Your settings">{name ? name.slice(0, 1).toUpperCase() : "you"}</Link>
    </div>
  </header>;
}
