import type { Citation } from "@/components/assistant-types";

/**
 * Renders `text` (the assistant's answer) with inline `[n]` markers turned
 * into small linked badges pointing at the matching card rendered below by
 * `<Sources>` - the Knowledge specialist's own citation convention (see
 * backend/app/agents/specialists/knowledge.py) is `[1]`, `[2]`, ... in
 * answer order, 1-indexed into the `citations` array exactly as returned by
 * the `sources` SSE event / `AssistantAskResponse.citations`.
 */
export function AnswerWithCitations({ text, citations }: { text: string; citations: Citation[] }) {
  const nodes: React.ReactNode[] = [];
  let lastIndex = 0;
  // A regex literal here (rather than module-level) is a fresh, unshared
  // `lastIndex` cursor per render - a shared module-level regex mutated
  // during render trips the react-hooks/immutability lint rule (and would
  // be a real bug under concurrent rendering).
  const citationMarker = /\[(\d+)\]/g;
  let match: RegExpExecArray | null;

  while ((match = citationMarker.exec(text)) !== null) {
    const n = Number(match[1]);
    const citation = citations[n - 1];
    nodes.push(text.slice(lastIndex, match.index));
    nodes.push(
      <sup key={`citation-marker-${match.index}`}>
        <a
          href={citation ? `#citation-${n}` : undefined}
          title={citation ? `${citation.source} - ${citation.section}` : undefined}
          className="mx-0.5 rounded-full bg-[var(--accent-soft)] px-1.5 py-0.5 text-[0.7em] font-semibold text-[var(--accent)] no-underline"
        >
          {n}
        </a>
      </sup>,
    );
    lastIndex = match.index + match[0].length;
  }
  nodes.push(text.slice(lastIndex));

  return <>{nodes}</>;
}

/** Source cards for one assistant message's citations - `[n] source - section` plus the grounding chunk text. */
export function Sources({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-2.5 flex flex-col gap-1.5">
      <p className="text-xs font-medium tracking-wide text-[var(--muted)] uppercase">Sources</p>
      {citations.map((citation, index) => (
        <div
          key={citation.chunk_id}
          id={`citation-${index + 1}`}
          className="scroll-mt-4 rounded-[calc(var(--radius)*0.6)] border border-[var(--border)] bg-[var(--surface-2)] p-2.5 text-xs"
        >
          <p className="font-medium text-[var(--ink)]">
            [{index + 1}] {citation.source} - {citation.section}
          </p>
          <p className="mt-1 text-[var(--muted)]">{citation.text}</p>
        </div>
      ))}
    </div>
  );
}
