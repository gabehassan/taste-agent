import "server-only";
import { headers } from "next/headers";

// The browser's address. Vercel overwrites both headers at its edge, so neither can be spoofed there.
export async function clientIp(): Promise<string | null> {
  const h = await headers();
  return h.get("x-real-ip") ?? h.get("x-forwarded-for")?.split(",")[0].trim() ?? null;
}

// The API rate limits by caller address, and every request from here leaves from the host's shared
// egress IPs. Pass the browser's address along with the secret the API uses to trust it.
export async function forwardedFor(): Promise<Record<string, string>> {
  const secret = process.env.DASHBOARD_PROXY_SECRET;
  const ip = secret ? await clientIp() : null;
  return secret && ip ? { "X-Taste-Client-IP": ip, "X-Taste-Proxy-Secret": secret } : {};
}
