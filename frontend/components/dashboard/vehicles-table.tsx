import type { VehicleDashboardRow } from "@/lib/dal";
import { formatDate, formatDays, formatKm } from "@/lib/format";
import { StatusPill } from "@/components/status-pill";

export function VehiclesTable({ vehicles }: { vehicles: VehicleDashboardRow[] }) {
  return (
    <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow)]">
      <div className="p-[var(--pad)] pb-0">
        <h2 className="text-sm font-medium text-[var(--muted)]">Vehicles</h2>
      </div>

      <div className="overflow-x-auto p-[var(--pad)]">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-xs text-[var(--muted)]">
              <th className="py-2 pr-4 font-medium">Vehicle</th>
              <th className="py-2 pr-4 font-medium">Last service</th>
              <th className="py-2 pr-4 font-medium">Odometer</th>
              <th className="py-2 pr-4 font-medium">Next service due</th>
              <th className="py-2 pr-4 font-medium">Days left</th>
              <th className="py-2 pr-0 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {vehicles.length === 0 && (
              <tr>
                <td colSpan={6} className="py-6 text-center text-[var(--muted)]">
                  No vehicles found.
                </td>
              </tr>
            )}
            {vehicles.map((vehicle) => (
              <tr
                key={vehicle.vehicleId}
                className="border-b border-[var(--border)] last:border-0"
              >
                <td className="py-3 pr-4">
                  <div className="font-medium text-[var(--ink)]">{vehicle.vehicleId}</div>
                  <div className="text-xs text-[var(--muted)]">
                    {[vehicle.year, vehicle.make, vehicle.vehicleModel].filter(Boolean).join(" ") || "—"}
                  </div>
                </td>
                <td className="py-3 pr-4 text-[var(--ink)]">{formatDate(vehicle.lastServiceDate)}</td>
                <td className="py-3 pr-4 text-[var(--ink)]">{formatKm(vehicle.lastServiceKm)}</td>
                <td className="py-3 pr-4 text-[var(--ink)]">{formatDate(vehicle.nextServiceDate)}</td>
                <td className="py-3 pr-4 tabular-nums text-[var(--ink)]">
                  {formatDays(vehicle.predictedDaysUntilService)}
                </td>
                <td className="py-3 pr-0">
                  <StatusPill status={vehicle.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
