import "server-only";

/**
 * Thin, server-only wrappers around the FastAPI backend.
 *
 * Every function here runs in Node (Route Handlers, Server Actions, the
 * DAL) - never in the browser - so calling FastAPI cross-origin is a
 * plain server-to-server fetch and never triggers a browser CORS
 * preflight. Nothing in this file reads or writes the BFF's own session
 * cookie; that's lib/session.ts's job. This file only knows how to talk
 * to FastAPI's own token contract (Bearer access tokens, an HttpOnly
 * refresh-token cookie scoped to /auth).
 */

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const REFRESH_COOKIE_NAME = "refresh_token";

export class BackendError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "BackendError";
  }
}

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
}

function extractRefreshToken(res: Response): string | null {
  const cookieValues = typeof res.headers.getSetCookie === "function" ? res.headers.getSetCookie() : [res.headers.get("set-cookie") ?? ""];

  for (const raw of cookieValues) {
    const match = raw.match(new RegExp(`${REFRESH_COOKIE_NAME}=([^;]+)`));
    if (match) return decodeURIComponent(match[1]);
  }
  return null;
}

/** POST /auth/login - exchanges credentials for an access token + refresh token. */
export async function loginToBackend(email: string, password: string): Promise<TokenPair> {
  const res = await fetch(`${BACKEND_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new BackendError(res.status, "Invalid email or password.");
  }

  const body = (await res.json()) as { access_token: string };
  const refreshToken = extractRefreshToken(res);
  if (!refreshToken) {
    throw new Error("Login succeeded but the backend did not set a refresh token cookie.");
  }

  return { accessToken: body.access_token, refreshToken };
}

/** POST /auth/refresh - rotates the refresh token and mints a new access token. */
export async function refreshBackendToken(refreshToken: string): Promise<TokenPair> {
  const res = await fetch(`${BACKEND_URL}/auth/refresh`, {
    method: "POST",
    headers: { Cookie: `${REFRESH_COOKIE_NAME}=${refreshToken}` },
    cache: "no-store",
  });

  if (!res.ok) {
    throw new BackendError(res.status, "Session expired.");
  }

  const body = (await res.json()) as { access_token: string };
  const rotatedRefreshToken = extractRefreshToken(res) ?? refreshToken;
  return { accessToken: body.access_token, refreshToken: rotatedRefreshToken };
}

/** POST /auth/logout - revokes the refresh token chain. Best-effort: logout proceeds locally either way. */
export async function logoutFromBackend(refreshToken: string): Promise<void> {
  await fetch(`${BACKEND_URL}/auth/logout`, {
    method: "POST",
    headers: { Cookie: `${REFRESH_COOKIE_NAME}=${refreshToken}` },
    cache: "no-store",
  }).catch(() => undefined);
}

export interface BackendResponse<T> {
  status: number;
  data: T | null;
}

/** Generic authenticated call to any other FastAPI route, using a Bearer access token. */
export async function backendRequest<T>(
  path: string,
  accessToken: string,
  init: RequestInit = {},
): Promise<BackendResponse<T>> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      Authorization: `Bearer ${accessToken}`,
    },
    cache: "no-store",
  });

  if (res.status === 204) {
    return { status: res.status, data: null };
  }

  let data: T | null = null;
  if (res.ok) {
    data = (await res.json()) as T;
  }

  return { status: res.status, data };
}
