"use server";

import { redirect } from "next/navigation";

import { BackendError } from "@/lib/api";
import { createVehicle } from "@/lib/dal";

export interface AddVehicleFormState {
  error?: string;
}

export async function createVehicleAction(
  _prevState: AddVehicleFormState,
  formData: FormData,
): Promise<AddVehicleFormState> {
  const vehicleId = formData.get("vehicleId");
  if (typeof vehicleId !== "string" || !vehicleId.trim()) {
    return { error: "Vehicle ID is required." };
  }

  const yearRaw = formData.get("year");
  const year = typeof yearRaw === "string" && yearRaw.trim() ? Number(yearRaw) : undefined;
  if (year !== undefined && !Number.isInteger(year)) {
    return { error: "Year must be a whole number." };
  }

  const make = formData.get("make");
  const vehicleModel = formData.get("vehicleModel");
  const fuelType = formData.get("fuelType");

  try {
    await createVehicle({
      vehicleId: vehicleId.trim(),
      make: typeof make === "string" && make ? make : undefined,
      vehicleModel: typeof vehicleModel === "string" && vehicleModel ? vehicleModel : undefined,
      year,
      fuelType: typeof fuelType === "string" && fuelType ? fuelType : undefined,
    });
  } catch (error) {
    if (error instanceof BackendError && error.status === 409) {
      return { error: `A vehicle with ID "${vehicleId.trim()}" already exists.` };
    }
    return { error: "Could not add the vehicle. Please try again." };
  }

  redirect("/dashboard");
}
