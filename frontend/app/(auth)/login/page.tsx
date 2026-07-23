import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--bg)] p-[var(--pad)]">
      <div className="w-full max-w-sm rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-[var(--pad)] shadow-[var(--shadow)]">
        <h1 className="text-xl font-semibold text-[var(--ink)]">Sign in to PitCrew</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Vehicle service predictions, live from the fleet.
        </p>
        <LoginForm />
      </div>
    </main>
  );
}
