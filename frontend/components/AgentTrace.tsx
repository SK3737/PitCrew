import type { TraceStep } from "@/components/assistant-types";

/**
 * Live agent-activity trace: Supervisor -> specialist steps, in the order
 * the backend's `trace` SSE events arrive (one per LangGraph node actually
 * visited - see backend/app/routers/assistant.py's `_stream_assistant_events`),
 * each with the real wall-clock duration between that node finishing and
 * the previous one. Not a simulated/decorative trace - `steps` is exactly
 * the trajectory this run took.
 */
export function AgentTrace({ steps, isActive }: { steps: TraceStep[]; isActive: boolean }) {
  return (
    <aside
      aria-label="Agent trace"
      className="flex flex-col gap-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-[var(--pad)] shadow-[var(--shadow)]"
    >
      <h2 className="text-sm font-semibold text-[var(--ink)]">Agent trace</h2>

      {steps.length === 0 && !isActive && (
        <p className="text-sm text-[var(--muted)]">Ask a question to see the agent trace.</p>
      )}

      {(steps.length > 0 || isActive) && (
        <ol className="flex flex-col gap-3">
          {steps.map((step, index) => (
            <li key={`${step.node}-${index}`} className="flex items-start gap-2.5">
              <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[var(--accent)]" />
              <div className="flex flex-1 flex-wrap items-baseline justify-between gap-x-2">
                <span className="text-sm text-[var(--ink)]">{step.label}</span>
                <span className="shrink-0 text-xs tabular-nums text-[var(--muted)]">
                  {step.durationMs.toFixed(0)} ms
                </span>
              </div>
            </li>
          ))}
          {isActive && (
            <li className="flex items-center gap-2.5">
              <span aria-hidden className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-[var(--warn)]" />
              <span className="text-sm text-[var(--muted)]">Working...</span>
            </li>
          )}
        </ol>
      )}
    </aside>
  );
}
