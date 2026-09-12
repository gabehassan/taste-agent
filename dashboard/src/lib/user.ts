import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const BASE = process.env.TASTE_API_URL!;
const COOKIE = "taste_user";
const TTL = 60 * 60 * 24 * 30;

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function userKey(): Promise<string | null> {
  const jar = await cookies();
  return jar.get(COOKIE)?.value ?? null;
}

export async function setUserKey(key: string) {
  const jar = await cookies();
  jar.set(COOKIE, key, { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: TTL });
}

export async function clearUserKey() {
  const jar = await cookies();
  jar.delete(COOKIE);
}

export async function userApi<T = any>(path: string, init: RequestInit = {}, key?: string | null): Promise<T> {
  const k = key ?? (await userKey());
  if (!k) redirect("/login");
  const res = await fetch(new URL(path, BASE), {
    ...init,
    headers: { Authorization: `Bearer ${k}`, "Content-Type": "application/json", ...(init.headers || {}) },
    cache: "no-store",
  });
  if (res.status === 401 || res.status === 403) redirect("/login?e=expired");
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch {}
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

export async function publicApi<T = any>(path: string, body: unknown): Promise<T> {
  const res = await fetch(new URL(path, BASE), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store" });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch {}
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

export const relTime = (s: string | null | undefined) => {
  if (!s) return "";
  const d = (Date.now() - new Date(s).getTime()) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  if (d < 86400 * 14) return `${Math.floor(d / 86400)}d ago`;
  return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric" });
};
