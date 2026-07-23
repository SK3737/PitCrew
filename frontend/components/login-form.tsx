"use client";

import { useActionState } from "react";

import { loginAction, type LoginFormState } from "@/app/(auth)/login/actions";

const initialState: LoginFormState = {};

export function LoginForm() {
  const [state, action, pending] = useActionState(loginAction, initialState);

  return (
    <form action={action} className="mt-6 flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="email" className="text-sm font-medium text-[var(--ink)]">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          required
          autoComplete="email"
          className="rounded-[calc(var(--radius)*0.5)] border border-[var(--border-strong)] bg-[var(--surface-2)] px-3 py-2 text-[var(--ink)] outline-none focus-visible:border-[var(--accent)]"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="password" className="text-sm font-medium text-[var(--ink)]">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          required
          autoComplete="current-password"
          className="rounded-[calc(var(--radius)*0.5)] border border-[var(--border-strong)] bg-[var(--surface-2)] px-3 py-2 text-[var(--ink)] outline-none focus-visible:border-[var(--accent)]"
        />
      </div>

      {state.error && (
        <p
          role="alert"
          className="rounded-[calc(var(--radius)*0.5)] bg-[var(--crit-soft)] px-3 py-2 text-sm text-[var(--crit)]"
        >
          {state.error}
        </p>
      )}

      <button
        type="submit"
        disabled={pending}
        className="mt-2 rounded-[calc(var(--radius)*0.5)] bg-[var(--accent)] px-4 py-2 font-medium text-[var(--accent-ink)] transition-opacity disabled:opacity-60"
      >
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
