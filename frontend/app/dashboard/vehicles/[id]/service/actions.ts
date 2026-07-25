"use server";

import { redirect } from "next/navigation";

import { BackendError } from "@/lib/api";
import { logService } from "@/lib/dal";

export interface LogServiceFormState {
  error?: string;
}

export async function logServiceAction(
  vehicleId: string,
  _prevState: LogServiceFormState,
  formData: FormData,
): Promise<LogServiceFormState> {
  const serviceDate = formData.get("serviceDate");
  if (typeof serviceDate !== "string" || !serviceDate) {
    return { error: "Service date is required." };
  }

  const odometerRaw = formData.get("odometerKm");
  const odometerKm = typeof odometerRaw === "string" ? Number(odometerRaw) : NaN;
  if (!Number.isFinite(odometerKm) || odometerKm < 0) {
    return { error: "Odometer reading must be a non-negative number." };
  }

  const serviceType = formData.get("serviceType");

  try {
    await logService({
      vehicleId,
      serviceDate,
      odometerKm,
      serviceType: typeof serviceType === "string" && serviceType ? serviceType : undefined,
    });
  } catch (error) {
    if (error instanceof BackendError && error.status === 403) {
      return { error: "You do not have permission to log service for this vehicle." };
    }
    return { error: "Could not record the service event. Please try again." };
  }

  redirect("/dashboard");
}
