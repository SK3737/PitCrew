import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { jwtVerify } from "jose";

const SESSION_COOKIE_NAME = "pitcrew_session";
const PUBLIC_ROUTES = new Set(["/login"]);

/**
 * Optimistic redirect ONLY - this is never the real authorization boundary.
 *
 * Next.js Proxy/Middleware (formerly "middleware.ts", renamed in v16 - see
 * app/getting-started guide) can be bypassed in vulnerable versions via a
 * crafted `x-middleware-subrequest` header (CVE-2025-29927), so it must
 * never be the only thing standing between a request and protected data.
 * This decrypts the cookie for a nicer UX (skip an obviously unauthenticated
 * render, don't bounce an authenticated user back to /login) - it is NOT a
 * substitute for the real check.
 *
 * ponytail: this must verify the JWT, not just check that the cookie
 * exists. dal.ts's verifySession() can't clear a stale/invalid cookie from
 * a Server Component render (Next.js only allows cookie writes from a
 * Server Action/Route Handler/Middleware), so an existence-only check here
 * would keep bouncing an invalid-but-present cookie between /login and
 * /dashboard forever - each side disagreeing about whether it counts as
 * "logged in".
 *
 * The actual authorization check lives in lib/dal.ts's `verifySession()`,
 * which every server component / Server Action / Route Handler that reads
 * backend data calls directly, decrypting the session and treating an
 * invalid/expired one as unauthenticated regardless of what Proxy decided.
 */
async function hasValidSession(request: NextRequest): Promise<boolean> {
  const raw = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  const secret = process.env.SESSION_SECRET;
  if (!raw || !secret) return false;
  try {
    await jwtVerify(raw, new TextEncoder().encode(secret), { algorithms: ["HS256"] });
    return true;
  } catch {
    return false;
  }
}

export default async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isPublicRoute = PUBLIC_ROUTES.has(pathname);
  const isValid = await hasValidSession(request);

  if (!isValid && !isPublicRoute) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (isValid && isPublicRoute) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
