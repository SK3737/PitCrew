import Link from "next/link";

import { verifySession } from "@/lib/dal";
import { LogServiceForm } from "@/components/vehicles/log-service-form";

export default async function LogServicePage({ params }: { params: Promise<{ id: string }> }) {
  await verifySession();
  const { id } = await params;

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--bg)] p-[var(--pad)]">
      <div className="w-full max-w-sm rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-[var(--pad)] shadow-[var(--shadow)]">
        <Link href="/dashboard" className="text-sm text-[var(--muted)] hover:text-[var(--ink)]">
          ← Back to dashboard
        </Link>
        <h1 className="mt-2 text-xl font-semibold text-[var(--ink)]">Log service for {id}</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">Record a completed service event.</p>
        <LogServiceForm vehicleId={id} />
      </div>
    </main>
  );
}
