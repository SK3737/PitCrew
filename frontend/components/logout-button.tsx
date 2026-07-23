import { redirect } from "next/navigation";

import { performLogout } from "@/lib/auth";

export function LogoutButton() {
  async function logout() {
    "use server";
    await performLogout();
    redirect("/login");
  }

  return (
    <form action={logout}>
      <button
        type="submit"
        className="rounded-[calc(var(--radius)*0.5)] border border-[var(--border-strong)] px-3 py-1.5 text-sm text-[var(--ink)] transition-colors hover:bg-[var(--surface-2)]"
      >
        Sign out
      </button>
    </form>
  );
}
