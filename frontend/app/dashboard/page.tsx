import { getKpis, getVehicles, verifySession } from "@/lib/dal";
import { KpiTiles } from "@/components/dashboard/kpi-tiles";
import { ServiceForecastChart } from "@/components/dashboard/service-forecast-chart";
import { NextServiceGauge } from "@/components/dashboard/next-service-gauge";
import { VehiclesTable } from "@/components/dashboard/vehicles-table";
import { LogoutButton } from "@/components/logout-button";

export default async function DashboardPage() {
  // The real auth check - not the optimistic one in proxy.ts. See lib/dal.ts.
  const session = await verifySession();
  const [kpis, vehicles] = await Promise.all([getKpis(), getVehicles()]);

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--ink)]">
      <header className="flex items-center justify-between border-b border-[var(--border)] px-[var(--pad)] py-4">
        <div>
          <h1 className="text-lg font-semibold">PitCrew</h1>
          <p className="text-sm text-[var(--muted)]">Fleet service dashboard</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-[var(--muted)] capitalize">{session.role}</span>
          <LogoutButton />
        </div>
      </header>

      <main className="flex flex-col gap-[var(--gap)] p-[var(--pad)]">
        <KpiTiles kpis={kpis} />

        <div className="grid grid-cols-1 gap-[var(--gap)] lg:grid-cols-3">
          <div className="lg:col-span-2">
            <ServiceForecastChart vehicles={vehicles} />
          </div>
          <NextServiceGauge kpis={kpis} />
        </div>

        <VehiclesTable vehicles={vehicles} />
      </main>
    </div>
  );
}
