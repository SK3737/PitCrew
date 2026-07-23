import { refreshBackendToken } from "@/lib/api";
import { deleteSession, getSession, updateSession } from "@/lib/session";

/**
 * BFF SSE proxy for the assistant chat.
 *
 * Why this exists instead of the browser calling FastAPI directly: the
 * FastAPI access token only ever lives in this server's encrypted session
 * cookie (see lib/session.ts) - the browser never sees it. And why this
 * can't be `EventSource`: `EventSource` only supports GET and cannot send
 * an `Authorization` header (or any custom header), so there is no way for
 * it to carry the bearer token FastAPI's `POST /assistant/stream` requires.
 * Instead: the browser's Chat.tsx does a plain `fetch("/api/assistant",
 * {method:"POST"})` (same-origin, so the HttpOnly `pitcrew_session` cookie
 * rides along automatically) and reads the response body itself via
 * `.body.getReader()`. This route reads that cookie, attaches the FastAPI
 * access token as a Bearer header when calling the backend, and re-streams
 * the backend's raw SSE bytes straight through as this route's own
 * response body - the browser never learns the access token exists.
 *
 * Not cached, not buffered: `dynamic = "force-dynamic"` stops Next from
 * treating this as a static/cacheable route now that it has no fixed body.
 */
export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

async function callBackendStream(accessToken: string, question: string): Promise<Response> {
  return fetch(`${BACKEND_URL}/assistant/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ question }),
    cache: "no-store",
  });
}

/**
 * Wraps the backend's `Response.body` in a new `ReadableStream` that pumps
 * bytes through via an explicit reader/controller loop (rather than handing
 * the backend stream back verbatim) so a browser disconnect cancels the
 * backend request too - `cancel()` here propagates to `reader.cancel()`,
 * which aborts the still-open fetch to FastAPI instead of leaving it
 * running to completion for a client that already gave up.
 */
function forwardAsReadableStream(backendBody: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  const reader = backendBody.getReader();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { done, value } = await reader.read();
      if (done) {
        controller.close();
        return;
      }
      controller.enqueue(value);
    },
    cancel(reason) {
      reader.cancel(reason).catch(() => undefined);
    },
  });
}

export async function POST(request: Request) {
  const session = await getSession();
  if (!session) {
    return Response.json({ error: "Not authenticated." }, { status: 401 });
  }

  const body = await request.json().catch(() => null);
  const question = typeof body?.question === "string" ? body.question.trim() : "";
  if (!question) {
    return Response.json({ error: "question is required." }, { status: 400 });
  }

  let accessToken = session.accessToken;
  let backendRes = await callBackendStream(accessToken, question);

  if (backendRes.status === 401) {
    try {
      const rotated = await refreshBackendToken(session.refreshToken);
      accessToken = rotated.accessToken;
      await updateSession({ ...session, accessToken: rotated.accessToken, refreshToken: rotated.refreshToken });
      backendRes = await callBackendStream(accessToken, question);
    } catch {
      await deleteSession();
      return Response.json({ error: "Session expired." }, { status: 401 });
    }
  }

  if (backendRes.status === 403) {
    return Response.json({ error: "You do not have permission to use the assistant." }, { status: 403 });
  }

  if (!backendRes.ok || !backendRes.body) {
    return Response.json({ error: "The assistant is unavailable right now." }, { status: backendRes.status || 502 });
  }

  return new Response(forwardAsReadableStream(backendRes.body), {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
