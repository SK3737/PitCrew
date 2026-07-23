import type { DashboardKpis } from "@/lib/dal";
import { formatDays } from "@/lib/format";

function Tile({
  label,
  value,
  accentVar,
}: {
  label: string;
  value: string;
  accentVar?: string;
}) {
  return (
    <div
      className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-[var(--pad)] shadow-[var(--shadow)]"
    >
      <p className="text-sm text-[var(--muted)]">{label}</p>
      <p
        className="mt-2 text-3xl font-semibold tabular-nums"
        style={accentVar ? { color: `var(${accentVar})` } : undefined}
      >
        {value}
      </p>
    </div>
  );
}

export function KpiTiles({ kpis }: { kpis: DashboardKpis }) {
  return (
    <section
      aria-label="Fleet summary"
      className="grid grid-cols-2 gap-[var(--gap)] lg:grid-cols-4"
    >
      <Tile label="Total vehicles" value={String(kpis.totalVehicles)} />
      <Tile label="On track" value={String(kpis.healthy)} accentVar="--good" />
      <Tile label="Due soon" value={String(kpis.dueSoon)} accentVar="--warn" />
      <Tile label="Overdue" value={String(kpis.overdue)} accentVar="--crit" />
    </section>
  );
}

export function nextServiceSummary(kpis: DashboardKpis): string {
  return formatDays(kpis.nextServiceInDays);
}
