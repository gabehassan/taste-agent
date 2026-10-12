import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { createHash, createHmac, timingSafeEqual } from "node:crypto";

const SECRET = process.env.DASHBOARD_SESSION_SECRET!;
const COOKIE = "taste_admin";
const TTL = 60 * 60 * 24 * 14;

function sign(payload: string) {
  return createHmac("sha256", SECRET).update(payload).digest("base64url");
}

export function makeToken() {
  const payload = `${Date.now() + TTL * 1000}`;
  return `${payload}.${sign(payload)}`;
}

export function verifyToken(tok: string | undefined) {
  if (!tok || !SECRET) return false;
  const [payload, sig] = tok.split(".");
  if (!payload || !sig) return false;
  const expect = sign(payload);
  if (sig.length !== expect.length || !timingSafeEqual(Buffer.from(sig), Buffer.from(expect))) return false;
  return Number(payload) > Date.now();
}

export async function requireSession() {
  const jar = await cookies();
  if (!verifyToken(jar.get(COOKIE)?.value)) redirect("/admin/login");
}

export async function setSession() {
  const jar = await cookies();
  jar.set(COOKIE, makeToken(), { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: TTL });
}

export async function clearSession() {
  const jar = await cookies();
  jar.delete(COOKIE);
}

export async function currentUserId(): Promise<string | null> {
  const jar = await cookies();
  return jar.get("taste_uid")?.value ?? null;
}

export async function setCurrentUserId(id: string) {
  const jar = await cookies();
  jar.set("taste_uid", id, { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: TTL });
}

// login attempts per instance: 5 per 15 min per ip
const attempts = new Map<string, { n: number; at: number }>();
export function loginAllowed(ip: string) {
  const now = Date.now();
  const a = attempts.get(ip);
  if (!a || now - a.at > 15 * 60 * 1000) { attempts.set(ip, { n: 1, at: now }); return true; }
  a.n += 1;
  return a.n <= 5;
}

export function passwordOk(pw: string) {
  const want = process.env.DASHBOARD_PASSWORD || "";
  if (!want) return false;
  // Compare fixed-length digests so neither the result nor the timing depends on the password length.
  const digest = (s: string) => createHash("sha256").update(s).digest();
  return timingSafeEqual(digest(pw), digest(want));
}
