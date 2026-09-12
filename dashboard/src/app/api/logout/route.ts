import { NextResponse } from "next/server";
import { clearUserKey, userKey } from "@/lib/user";

export async function POST(req: Request) {
  const k = await userKey();
  if (k) { try { await fetch(new URL("/v1/auth/logout", process.env.TASTE_API_URL!), { method: "POST", headers: { Authorization: `Bearer ${k}` } }); } catch {} }
  await clearUserKey();
  return NextResponse.redirect(new URL("/login", req.url), 303);
}
