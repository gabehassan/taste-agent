"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "motion/react";

const NAV = [["/", "home"], ["/items", "library"], ["/taste", "taste"], ["/connections", "connections"], ["/settings", "settings"]];

export default function Nav({ name }: { name: string }) {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-20 backdrop-blur-md" style={{ background: "color-mix(in oklab, var(--paper) 82%, transparent)" }}>
      <div className="mx-auto max-w-5xl px-5 py-4 flex items-center gap-6">
        <Link href="/" className="display text-2xl">taste<span style={{ color: "var(--accent)" }}>.</span></Link>
        <nav className="flex gap-1 ml-2">
          {NAV.map(([href, label]) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link key={href} href={href} className="relative px-3 py-1.5 text-sm rounded-full" style={{ color: active ? "var(--ink)" : "var(--ink-2)" }}>
                {active && <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-full" style={{ background: "var(--paper-2)" }} transition={{ type: "spring", stiffness: 400, damping: 32 }} />}
                <span className="relative">{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto text-sm u-muted">{name}</div>
        <form action="/api/logout" method="post"><button className="text-sm u-faint hover:underline">log out</button></form>
      </div>
    </header>
  );
}
