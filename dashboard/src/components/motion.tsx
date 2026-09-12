"use client";
import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

export const ease = [0.25, 0.1, 0.25, 1] as const;

export function Fade({ children, delay = 0, y = 4, className }: { children: ReactNode; delay?: number; y?: number; className?: string }) {
  const reduced = useReducedMotion();
  return <motion.div initial={reduced ? false : { opacity: 0, y }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay, ease }} className={className}>{children}</motion.div>;
}

export function Stagger({ children, className, gap = 0.03 }: { children: ReactNode; className?: string; gap?: number }) {
  return <motion.div className={className} initial="hidden" animate="show" variants={{ hidden: {}, show: { transition: { staggerChildren: gap } } }}>{children}</motion.div>;
}

export function Item({ children, className }: { children: ReactNode; className?: string }) {
  return <motion.div className={className} variants={{ hidden: { opacity: 0 }, show: { opacity: 1, transition: { duration: 0.3, ease } } }}>{children}</motion.div>;
}

export function Words({ text, className, delay = 0 }: { text: string; className?: string; delay?: number }) {
  return <motion.span className={className} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay, ease }}>{text}</motion.span>;
}

export function Presence({ children }: { children: ReactNode }) { return <AnimatePresence mode="wait">{children}</AnimatePresence>; }
export function Count({ n }: { n: number }) { return <span>{n}</span>; }
