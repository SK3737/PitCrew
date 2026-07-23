import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE_NAME = "pitcrew_session";
const PUBLIC_ROUTES = new Set(["/login"]);

/**
 * Optimistic redirect ONLY - this is never the real authorization boundary.
 *
 * Next.js Proxy/Middleware (formerly "middleware.ts", renamed in v16 - see
 * app/getting-started guide) can be bypassed in vulnerable versions via a
 * crafted `x-middleware-subrequest` header (CVE-2025-29927), so it must
 * never be the only thing standing between a request and protected data.
 * This just checks whether a session cookie *exists*, to skip an obviously
 * unauthenticated render for a nicer UX (early redirect to /login without
 * waiting on a render pass). It does not decrypt or validate the cookie.
 *
 * The actual authorization check lives in lib/dal.ts's `verifySession()`,
 * which every server component / Server Action / Route Handler that reads
 * backend data calls directly, decrypting the session and treating an
 * invalid/expired one as unauthenticated regardless of what Proxy decided.
 */
export default function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSessionCookie = request.cookies.has(SESSION_COOKIE_NAME);
  const isPublicRoute = PUBLIC_ROUTES.has(pathname);

  if (!hasSessionCookie && !isPublicRoute) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (hasSessionCookie && isPublicRoute) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
