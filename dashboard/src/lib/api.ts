import "server-only";

const BASE = process.env.TASTE_API_URL!;
const KEY = process.env.TASTE_ADMIN_KEY!;

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = any>(path: string, init: RequestInit & { userId?: string | null } = {}): Promise<T> {
  const { userId, ...rest } = init;
  const url = new URL(path, BASE);
  if (userId) url.searchParams.set("user_id", userId);
  const res = await fetch(url, {
    ...rest,
    headers: { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json", ...(rest.headers || {}) },
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
export const fmtDate = (s: string | null | undefined) => (s ? new Date(s).toLocaleString("en-US", { timeZone: "America/Detroit" }) : "");
