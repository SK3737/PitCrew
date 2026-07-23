import { NextResponse } from "next/server";

import { performLogout } from "@/lib/auth";

/** BFF logout endpoint - revokes the refresh token at FastAPI and clears the session cookie. */
export async function POST() {
  await performLogout();
  return NextResponse.json({ ok: true });
}
