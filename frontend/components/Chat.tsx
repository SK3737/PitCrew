"use client";

import { useState } from "react";

import { AgentTrace } from "@/components/AgentTrace";
import type { ChatMessage } from "@/components/assistant-types";
import { AnswerWithCitations, Sources } from "@/components/Sources";

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Parses one complete SSE message block (the text between two `\n\n`
 * separators - see backend/app/routers/assistant.py's `_sse` helper for the
 * writer side) into its `event`/`data` pair. Returns null for a malformed
 * block rather than throwing, since a dropped/garbled event should never
 * crash the whole chat stream.
 */
function parseSSEBlock(block: string): { event: string; data: Record<string, unknown> } | null {
  const eventLine = block.split("\n").find((line) => line.startsWith("event: "));
  const dataLine = block.split("\n").find((line) => line.startsWith("data: "));
  if (!eventLine || !dataLine) return null;
  try {
    return {
      event: eventLine.slice("event: ".length),
      data: JSON.parse(dataLine.slice("data: ".length)),
    };
  } catch {
    return null;
  }
}

export function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);

  function patchMessage(id: string, patch: (message: ChatMessage) => ChatMessage) {
    setMessages((prev) => prev.map((message) => (message.id === id ? patch(message) : message)));
  }

  function applyServerEvent(assistantId: string, event: string, data: Record<string, unknown>) {
    switch (event) {
      case "trace":
        patchMessage(assistantId, (message) => ({
          ...message,
          trace: [
            ...message.trace,
            {
              node: String(data.node),
              label: String(data.label ?? data.node),
              durationMs: Number(data.duration_ms ?? 0),
            },
          ],
        }));
        break;
      case "token":
        patchMessage(assistantId, (message) => ({ ...message, content: message.content + String(data.text ?? "") }));
        break;
      case "sources":
        patchMessage(assistantId, (message) => ({
          ...message,
          citations: Array.isArray(data.citations) ? (data.citations as ChatMessage["citations"]) : [],
        }));
        break;
      case "done":
        patchMessage(assistantId, (message) => ({
          ...message,
          status: "done",
          content: typeof data.answer === "string" ? data.answer : message.content,
        }));
        break;
      case "error":
        patchMessage(assistantId, (message) => ({
          ...message,
          status: "error",
          errorMessage: typeof data.message === "string" ? data.message : "The assistant hit an error.",
        }));
        break;
    }
  }

  // fetch + response.body.getReader() - deliberately not `EventSource`,
  // which only supports GET and cannot attach the session's auth cookie
  // the way a same-origin POST already does automatically. See
  // app/api/assistant/route.ts's module docstring for the full rationale.
  async function streamAssistantReply(assistantId: string, submittedQuestion: string) {
    const response = await fetch("/api/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: submittedQuestion }),
    });

    if (!response.ok || !response.body) {
      const body = await response.json().catch(() => ({ error: "The assistant is unavailable right now." }));
      patchMessage(assistantId, (message) => ({
        ...message,
        status: "error",
        errorMessage: typeof body.error === "string" ? body.error : "The assistant is unavailable right now.",
      }));
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex !== -1) {
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);
        const parsed = parseSSEBlock(block);
        if (parsed) applyServerEvent(assistantId, parsed.event, parsed.data);
        separatorIndex = buffer.indexOf("\n\n");
      }
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isStreaming) return;

    const userMessage: ChatMessage = {
      id: newId(),
      role: "user",
      content: trimmed,
      citations: [],
      trace: [],
      status: "done",
    };
    const assistantId = newId();
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      citations: [],
      trace: [],
      status: "streaming",
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setQuestion("");
    setIsStreaming(true);

    try {
      await streamAssistantReply(assistantId, trimmed);
    } catch {
      patchMessage(assistantId, (message) => ({
        ...message,
        status: "error",
        errorMessage: "Connection to the assistant was lost.",
      }));
    } finally {
      setIsStreaming(false);
    }
  }

  const lastAssistantMessage = [...messages].reverse().find((message) => message.role === "assistant");

  return (
    <div className="grid grid-cols-1 gap-[var(--gap)] lg:grid-cols-3">
      <div className="flex flex-col gap-[var(--gap)] lg:col-span-2">
        <div
          role="log"
          aria-label="Conversation"
          className="flex min-h-[420px] flex-col gap-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-[var(--pad)] shadow-[var(--shadow)]"
        >
          {messages.length === 0 && (
            <p className="text-sm text-[var(--muted)]">
              Ask about a vehicle&apos;s next service, general maintenance, or book an appointment.
            </p>
          )}
          {messages.map((message) => (
            <ChatBubble key={message.id} message={message} />
          ))}
        </div>

        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask the assistant..."
            aria-label="Question"
            disabled={isStreaming}
            className="flex-1 rounded-[calc(var(--radius)*0.6)] border border-[var(--border-strong)] bg-[var(--surface-2)] px-3 py-2 text-sm text-[var(--ink)] placeholder:text-[var(--faint)] focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={isStreaming || !question.trim()}
            className="rounded-[calc(var(--radius)*0.6)] bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-ink)] transition-opacity disabled:opacity-50"
          >
            {isStreaming ? "Thinking..." : "Ask"}
          </button>
        </form>
      </div>

      <AgentTrace steps={lastAssistantMessage?.trace ?? []} isActive={isStreaming} />
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-[calc(var(--radius)*0.8)] px-3.5 py-2.5 text-sm ${
          isUser ? "bg-[var(--accent)] text-[var(--accent-ink)]" : "bg-[var(--surface-2)] text-[var(--ink)]"
        }`}
      >
        {message.status === "error" ? (
          <p className="text-[var(--crit)]">{message.errorMessage}</p>
        ) : (
          <>
            <p className="whitespace-pre-wrap">
              <AnswerWithCitations text={message.content} citations={message.citations} />
              {message.status === "streaming" && <span className="animate-pulse">&#9615;</span>}
            </p>
            <Sources citations={message.citations} />
          </>
        )}
      </div>
    </div>
  );
}
