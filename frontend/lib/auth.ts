import "server-only";

import { decodeJwt } from "jose";

import { BackendError, loginToBackend, logoutFromBackend } from "@/lib/api";
import { createSession, deleteSession, getSession, type Role } from "@/lib/session";

export { BackendError };

interface AccessTokenClaims {
  sub: string;
  role: Role;
}

/**
 * Exchanges credentials with FastAPI and stores the result in the BFF's
 * session cookie. Never redirects itself - callers (a Server Action, or a
 * Route Handler) decide how to respond to success/failure.
 *
 * The access token is decoded (not re-verified) purely to read `sub`/`role`
 * for the session payload - it just came back over a direct, trusted
 * server-to-server call to FastAPI, so re-verifying its own signature here
 * would be redundant.
 */
export async function performLogin(email: string, password: string): Promise<void> {
  const { accessToken, refreshToken } = await loginToBackend(email, password);
  const claims = decodeJwt(accessToken) as unknown as AccessTokenClaims;

  await createSession({
    userId: Number(claims.sub),
    role: claims.role,
    accessToken,
    refreshToken,
  });
}

export async function performLogout(): Promise<void> {
  const session = await getSession();
  if (session) {
    await logoutFromBackend(session.refreshToken);
  }
  await deleteSession();
}
