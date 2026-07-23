import Link from "next/link";

import { verifySession } from "@/lib/dal";
import { Chat } from "@/components/Chat";
import { LogoutButton } from "@/components/logout-button";

export default async function AssistantPage() {
  // The real auth check - not the optimistic one in proxy.ts. See lib/dal.ts.
  // Per-question authorization (use_assistant/use_assistant_replay) is
  // still enforced server-side by FastAPI on every /assistant/stream call;
  // a signed-in user whose role lacks that permission sees a friendly error
  // bubble instead of an answer rather than being blocked from this page.
  const session = await verifySession();

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--ink)]">
      <header className="flex items-center justify-between border-b border-[var(--border)] px-[var(--pad)] py-4">
        <div>
          <h1 className="text-lg font-semibold">PitCrew</h1>
          <p className="text-sm text-[var(--muted)]">Service assistant</p>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/dashboard" className="text-sm text-[var(--muted)] hover:text-[var(--ink)]">
            Dashboard
          </Link>
          <span className="text-sm text-[var(--muted)] capitalize">{session.role}</span>
          <LogoutButton />
        </div>
      </header>

      <main className="p-[var(--pad)]">
        <Chat />
      </main>
    </div>
  );
}
