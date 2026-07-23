/**
 * Shared shapes for the assistant chat UI (Chat/Sources/AgentTrace).
 *
 * Mirrors the backend's SSE event payloads (see
 * backend/app/routers/assistant.py's `_stream_assistant_events`) and its
 * `AssistantAskResponse`/`KBHit` schemas - kept as plain data types here
 * (camelCase where derived, snake_case preserved where it's a citation
 * field lifted straight off the wire) rather than re-declared per
 * component, since all three components render the same run's data.
 */

export interface Citation {
  chunk_id: number;
  source: string;
  section: string;
  text: string;
  score: number;
}

export interface TraceStep {
  node: string;
  label: string;
  durationMs: number;
}

export type MessageStatus = "streaming" | "done" | "error";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  trace: TraceStep[];
  status: MessageStatus;
  errorMessage?: string;
}
