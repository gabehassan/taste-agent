import "server-only";
import { forwardedFor } from "@/lib/client-ip";
import { requireSession } from "@/lib/session";

const BASE = process.env.TASTE_API_URL!;
const KEY = process.env.TASTE_ADMIN_KEY!;

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// Every request made with the admin key runs on behalf of a signed-in admin. Server actions are
// public POST endpoints, so this check cannot live only in the pages that render the forms.
export async function api<T = unknown>(path: string, init: RequestInit & { userId?: string | null } = {}): Promise<T> {
  await requireSession();
  const { userId, ...rest } = init;
  const url = new URL(path, BASE);
  if (userId) url.searchParams.set("user_id", userId);
  const res = await fetch(url, {
    ...rest,
    headers: { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json", ...(await forwardedFor()), ...(rest.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail ?? msg; } catch {}
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

export const fmtMoney = (n: number | string | null | undefined) => `$${Number(n ?? 0).toFixed(2)}`;
export const fmtDate = (s: string | null | undefined) => (s ? new Date(s).toLocaleString("en-US", { timeZone: process.env.DASHBOARD_TZ || "UTC" }) : "");
