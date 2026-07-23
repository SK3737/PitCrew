import "server-only";

import { cache } from "react";
import { redirect } from "next/navigation";

import { backendRequest, refreshBackendToken } from "@/lib/api";
import { deleteSession, getSession, updateSession, type SessionPayload } from "@/lib/session";

/**
 * Data Access Layer.
 *
 * This is the real authorization boundary (see proxy.ts for why it can't
 * live in Proxy/Middleware alone - CVE-2025-29927). Every server component
 * or Server Action that needs backend data goes through `verifySession()`
 * here, not through a cookie check anywhere else.
 */
export const verifySession = cache(async (): Promise<SessionPayload> => {
  const session = await getSession();
  if (!session) {
    redirect("/login");
  }
  return session;
});

/**
 * Calls a FastAPI route with the session's access token, transparently
 * refreshing once (via the BFF-held refresh token) if the access token
 * (15 min lifetime) has expired. Redirects to /login if refreshing also
 * fails, since that means the whole session is no longer valid.
 */
async function authedRequest<T>(path: string, init?: RequestInit): Promise<T>;
async function authedRequest<T>(
  path: string,
  init: RequestInit | undefined,
  options: { allow404: true },
): Promise<T | null>;
async function authedRequest<T>(
  path: string,
  init?: RequestInit,
  options?: { allow404?: boolean },
): Promise<T | null> {
  let session = await verifySession();
  let { status, data } = await backendRequest<T>(path, session.accessToken, init);

  if (status === 401) {
    try {
      const rotated = await refreshBackendToken(session.refreshToken);
      session = { ...session, accessToken: rotated.accessToken, refreshToken: rotated.refreshToken };
      await updateSession(session);
      ({ status, data } = await backendRequest<T>(path, session.accessToken, init));
    } catch {
      await deleteSession();
      redirect("/login");
    }
  }

  if (status === 401) {
    await deleteSession();
    redirect("/login");
  }
  if (status === 403) {
    throw new Error("You do not have permission to view this data.");
  }
  if (status === 404 && options?.allow404) {
    return null;
  }
  if (data === null) {
    throw new Error(`Request to ${path} failed with status ${status}.`);
  }
  return data;
}

// --- FastAPI response shapes (snake_case, as returned by the backend) -----

interface BackendVehicleSummary {
  vehicle_id: string;
  make: string | null;
  vehicle_model: string | null;
  year: number | null;
  fuel_type: string | null;
}

interface BackendHistory {
  vehicle_id: string;
  last_service_date: string | null;
  last_service_km: number | null;
  empirical_km_per_month: number | null;
}

interface BackendPrediction {
  predicted_days_until_service: number;
  predicted_kms_until_service: number;
  earlier_trigger: "time" | "km";
  next_service_date: string;
  next_service_km: number | null;
  source: "model_v2" | "model_v1" | "rules";
}

// --- Dashboard-shaped data transfer objects --------------------------------

export type ServiceStatus = "good" | "warn" | "crit" | "unknown";

export interface VehicleDashboardRow {
  vehicleId: string;
  make: string | null;
  vehicleModel: string | null;
  year: number | null;
  fuelType: string | null;
  lastServiceDate: string | null;
  lastServiceKm: number | null;
  predictedDaysUntilService: number | null;
  predictedKmUntilService: number | null;
  nextServiceDate: string | null;
  status: ServiceStatus;
}

/**
 * Status thresholds map onto the reserved --good/--warn/--crit tokens:
 * crit = already due (days or km exhausted), warn = approaching the
 * threshold, good = comfortably ahead of it.
 */
function statusFor(days: number | null, km: number | null): ServiceStatus {
  if (days === null || km === null) return "unknown";
  if (days <= 0 || km <= 0) return "crit";
  if (days <= 14 || km <= 500) return "warn";
  return "good";
}

/**
 * There is no live telemetry feed for "current odometer", so the dashboard
 * predicts as of the vehicle's last recorded service reading (i.e. assumes
 * no extra km driven since then). `months_driven` still varies per vehicle
 * based on each one's real last-service date, so predicted days-until-due
 * still spans good/warn/crit across the fleet - just conservatively, since
 * any actual driving since the last service would only pull dates closer.
 */
const getDashboardRows = cache(async (): Promise<VehicleDashboardRow[]> => {
  const summaries = await authedRequest<BackendVehicleSummary[]>("/vehicles/");

  const empty = {
    lastServiceDate: null,
    lastServiceKm: null,
    predictedDaysUntilService: null,
    predictedKmUntilService: null,
    nextServiceDate: null,
    status: "unknown" as const,
  };

  return Promise.all(
    summaries.map(async (vehicle): Promise<VehicleDashboardRow> => {
      const base = {
        vehicleId: vehicle.vehicle_id,
        make: vehicle.make,
        vehicleModel: vehicle.vehicle_model,
        year: vehicle.year,
        fuelType: vehicle.fuel_type,
      };

      // No service history recorded yet (404) - show the vehicle without a
      // prediction rather than failing the whole dashboard.
      const history = await authedRequest<BackendHistory>(`/vehicles/${vehicle.vehicle_id}/history`, undefined, {
        allow404: true,
      });
      if (history === null || history.last_service_km === null) {
        return { ...base, ...empty };
      }

      const prediction = await authedRequest<BackendPrediction>(`/vehicles/${vehicle.vehicle_id}/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_odometer_km: history.last_service_km }),
      });
      if (prediction === null) {
        return { ...base, ...empty };
      }

      return {
        ...base,
        lastServiceDate: history.last_service_date,
        lastServiceKm: history.last_service_km,
        predictedDaysUntilService: prediction.predicted_days_until_service,
        predictedKmUntilService: prediction.predicted_kms_until_service,
        nextServiceDate: prediction.next_service_date,
        status: statusFor(prediction.predicted_days_until_service, prediction.predicted_kms_until_service),
      };
    }),
  );
});

export async function getVehicles(): Promise<VehicleDashboardRow[]> {
  return getDashboardRows();
}

export interface DashboardKpis {
  totalVehicles: number;
  healthy: number;
  dueSoon: number;
  overdue: number;
  nextServiceInDays: number | null;
}

export async function getKpis(): Promise<DashboardKpis> {
  const rows = await getDashboardRows();
  const knownDays = rows
    .map((row) => row.predictedDaysUntilService)
    .filter((days): days is number => days !== null);

  return {
    totalVehicles: rows.length,
    healthy: rows.filter((row) => row.status === "good").length,
    dueSoon: rows.filter((row) => row.status === "warn").length,
    overdue: rows.filter((row) => row.status === "crit").length,
    nextServiceInDays: knownDays.length ? Math.min(...knownDays) : null,
  };
}
