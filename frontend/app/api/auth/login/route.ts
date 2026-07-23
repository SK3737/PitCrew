import { NextResponse } from "next/server";

import { BackendError, performLogin } from "@/lib/auth";

/**
 * BFF login endpoint - forwards credentials to FastAPI's POST /auth/login
 * and, on success, stores the access + refresh tokens in this server's own
 * encrypted session cookie (see lib/session.ts). Only a success/failure
 * flag is ever sent back in the response body; neither token is exposed to
 * the browser.
 *
 * The login page's Server Action (app/(auth)/login/actions.ts) calls
 * `performLogin` directly rather than round-tripping through this route -
 * a Server Action can set the session cookie on its own response, whereas a
 * same-process fetch from the action to this route would only see the
 * cookie on the internal response, not the one sent to the browser. This
 * route exists as the callable BFF endpoint for any other client (e.g. a
 * non-JS form post, or a future mobile/API client) that needs the same
 * exchange over a plain HTTP call.
 */
export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const email = typeof body?.email === "string" ? body.email : null;
  const password = typeof body?.password === "string" ? body.password : null;

  if (!email || !password) {
    return NextResponse.json({ error: "Email and password are required." }, { status: 400 });
  }

  try {
    await performLogin(email, password);
  } catch (error) {
    if (error instanceof BackendError) {
      return NextResponse.json({ error: "Invalid email or password." }, { status: 401 });
    }
    throw error;
  }

  return NextResponse.json({ ok: true });
}
