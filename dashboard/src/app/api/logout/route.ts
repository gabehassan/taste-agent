import { NextResponse } from "next/server";
import { clearSession } from "@/lib/session";

export async function POST(req: Request) {
  await clearSession();
  return NextResponse.redirect(new URL("/login", req.url), 303);
}
