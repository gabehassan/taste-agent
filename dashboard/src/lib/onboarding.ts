import "server-only";
import { connection } from "next/server";
import { forwardedFor } from "@/lib/client-ip";

export type OnboardingConfig = { phone: string | null; open_signup: boolean };

// Read per request: a page prerendered at build time would freeze whatever the API said then.
export async function onboardingConfig(): Promise<OnboardingConfig | null> {
  await connection();
  try {
    const res = await fetch(new URL("/v1/public/config", process.env.TASTE_API_URL!), { headers: await forwardedFor(), cache: "no-store", signal: AbortSignal.timeout(5000) });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

export function messageLink(phone: string, body?: string) {
  return `sms:${phone}${body ? `?body=${encodeURIComponent(body)}` : ""}`;
}
