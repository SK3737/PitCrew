import type { VehicleDashboardRow } from "@/lib/dal";
import { STATUS_COLOR_VAR } from "@/lib/format";
import { formatDays } from "@/lib/format";

/**
 * Predicted-services chart: one hue family (the reserved good/warn/crit
 * status tokens - never a decorative rainbow), no legend - each bar carries
 * its own direct label instead.
 */
export function ServiceForecastChart({ vehicles }: { vehicles: VehicleDashboardRow[] }) {
  const known = vehicles.filter((v) => v.predictedDaysUntilService !== null);
  const sorted = [...known].sort(
    (a, b) => (a.predictedDaysUntilService ?? 0) - (b.predictedDaysUntilService ?? 0),
  );
  const maxDays = Math.max(1, ...sorted.map((v) => Math.max(v.predictedDaysUntilService ?? 0, 0)));

  return (
    <div className="h-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-[var(--pad)] shadow-[var(--shadow)]">
      <h2 className="text-sm font-medium text-[var(--muted)]">Predicted next service</h2>
      <p className="mt-1 text-xs text-[var(--faint)]">Days until each vehicle&apos;s next service is due</p>

      <div className="mt-[var(--gap)] flex flex-col gap-3">
        {sorted.length === 0 && (
          <p className="text-sm text-[var(--muted)]">No predictions available yet.</p>
        )}
        {sorted.map((vehicle) => {
          const days = Math.max(vehicle.predictedDaysUntilService ?? 0, 0);
          const widthPct = Math.max((days / maxDays) * 100, 4);
          const colorVar = STATUS_COLOR_VAR[vehicle.status];
          return (
            <div key={vehicle.vehicleId} className="flex items-center gap-3">
              <span className="w-24 shrink-0 truncate text-xs text-[var(--muted)]">
                {vehicle.vehicleId}
              </span>
              <div className="relative h-6 flex-1 rounded-full bg-[var(--surface-2)]">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${widthPct}%`, backgroundColor: `var(${colorVar})` }}
                />
              </div>
              <span className="w-20 shrink-0 text-right text-xs font-medium tabular-nums text-[var(--ink)]">
                {formatDays(vehicle.predictedDaysUntilService)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
