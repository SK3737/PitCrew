import type { ServiceStatus } from "@/lib/dal";

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatKm(km: number | null): string {
  if (km === null) return "—";
  return `${Math.round(km).toLocaleString("en-US")} km`;
}

export function formatDays(days: number | null): string {
  if (days === null) return "—";
  if (days <= 0) return "Overdue";
  return `${days} ${days === 1 ? "day" : "days"}`;
}

export const STATUS_LABEL: Record<ServiceStatus, string> = {
  good: "On track",
  warn: "Due soon",
  crit: "Overdue",
  unknown: "No data",
};

/** Maps a status to its reserved Midnight Indigo token names (never reused decoratively elsewhere). */
export const STATUS_COLOR_VAR: Record<ServiceStatus, string> = {
  good: "--good",
  warn: "--warn",
  crit: "--crit",
  unknown: "--faint",
};

export const STATUS_SOFT_VAR: Record<ServiceStatus, string> = {
  good: "--good-soft",
  warn: "--warn-soft",
  crit: "--crit-soft",
  unknown: "--surface-2",
};
