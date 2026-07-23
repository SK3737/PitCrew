import "server-only";

import { SignJWT, jwtVerify, type JWTPayload } from "jose";
import { cookies } from "next/headers";

/**
 * The BFF's own encrypted session cookie.
 *
 * This is where the FastAPI access token lives - server-side only. It is
 * NEVER sent to the browser as a plain, JS-readable cookie and never
 * appears in a client-visible response body; the browser only ever holds
 * this one HttpOnly cookie (an opaque signed blob), and every call to
 * FastAPI is made from Node (this file / lib/dal.ts), never from client JS.
 */

export type Role = "admin" | "mechanic" | "owner" | "demo";

export interface SessionPayload extends JWTPayload {
  userId: number;
  role: Role;
  accessToken: string;
  refreshToken: string;
}

const SESSION_COOKIE_NAME = "pitcrew_session";
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14; // matches backend REFRESH_TOKEN_DAYS default

function getEncodedKey(): Uint8Array {
  const secret = process.env.SESSION_SECRET;
  if (!secret) {
    throw new Error("SESSION_SECRET environment variable is required to run the BFF.");
  }
  return new TextEncoder().encode(secret);
}

async function encrypt(payload: SessionPayload): Promise<string> {
  return new SignJWT(payload)
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(`${SESSION_MAX_AGE_SECONDS}s`)
    .sign(getEncodedKey());
}

async function decrypt(session: string | undefined): Promise<SessionPayload | null> {
  if (!session) return null;
  try {
    const { payload } = await jwtVerify(session, getEncodedKey(), { algorithms: ["HS256"] });
    return payload as SessionPayload;
  } catch {
    return null;
  }
}

async function setSessionCookie(payload: SessionPayload): Promise<void> {
  const token = await encrypt(payload);
  const cookieStore = await cookies();
  cookieStore.set(SESSION_COOKIE_NAME, token, {
    httpOnly: true,
    secure: true,
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
}

export async function createSession(payload: SessionPayload): Promise<void> {
  await setSessionCookie(payload);
}

/** Re-encrypts and re-sets the cookie after a token refresh. */
export async function updateSession(payload: SessionPayload): Promise<void> {
  await setSessionCookie(payload);
}

export async function deleteSession(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE_NAME);
}

/** Reads + decrypts the session cookie. Returns null if absent/invalid - callers decide what to do. */
export async function getSession(): Promise<SessionPayload | null> {
  const cookieStore = await cookies();
  const raw = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  return decrypt(raw);
}
