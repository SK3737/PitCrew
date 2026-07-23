import type { DashboardKpis, ServiceStatus } from "@/lib/dal";
import { STATUS_COLOR_VAR } from "@/lib/format";

const RADIUS = 54;
const STROKE = 10;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const HORIZON_DAYS = 90; // ring is "empty" (no urgency) at this far out or beyond

function statusForDays(days: number | null): ServiceStatus {
  if (days === null) return "unknown";
  if (days <= 0) return "crit";
  if (days <= 14) return "warn";
  return "good";
}

export function NextServiceGauge({ kpis }: { kpis: DashboardKpis }) {
  const days = kpis.nextServiceInDays;
  const status = statusForDays(days);
  const clampedDays = days === null ? HORIZON_DAYS : Math.min(Math.max(days, 0), HORIZON_DAYS);
  const urgencyFraction = 1 - clampedDays / HORIZON_DAYS;
  const dashOffset = CIRCUMFERENCE * (1 - urgencyFraction);
  const colorVar = STATUS_COLOR_VAR[status];

  return (
    <div className="flex flex-col items-center rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-[var(--pad)] shadow-[var(--shadow)]">
      <h2 className="self-start text-sm font-medium text-[var(--muted)]">Soonest service due</h2>

      <div className="relative mt-4 h-36 w-36">
        <svg viewBox="0 0 140 140" className="h-36 w-36 -rotate-90">
          <circle cx="70" cy="70" r={RADIUS} fill="none" stroke="var(--surface-2)" strokeWidth={STROKE} />
          <circle
            cx="70"
            cy="70"
            r={RADIUS}
            fill="none"
            stroke={`var(${colorVar})`}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={dashOffset}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-semibold tabular-nums text-[var(--ink)]">
            {days === null ? "—" : Math.max(days, 0)}
          </span>
          <span className="text-xs text-[var(--muted)]">
            {days === null ? "no data" : days <= 0 ? "days overdue" : "days left"}
          </span>
        </div>
      </div>
    </div>
  );
}
