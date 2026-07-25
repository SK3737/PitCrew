"use client";

import { useActionState } from "react";

import { createVehicleAction, type AddVehicleFormState } from "@/app/dashboard/vehicles/new/actions";

const initialState: AddVehicleFormState = {};

const inputClass =
  "rounded-[calc(var(--radius)*0.5)] border border-[var(--border-strong)] bg-[var(--surface-2)] px-3 py-2 text-[var(--ink)] outline-none focus-visible:border-[var(--accent)]";

export function AddVehicleForm() {
  const [state, action, pending] = useActionState(createVehicleAction, initialState);

  return (
    <form action={action} className="mt-6 flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="vehicleId" className="text-sm font-medium text-[var(--ink)]">
          Vehicle ID / plate
        </label>
        <input
          id="vehicleId"
          name="vehicleId"
          type="text"
          required
          placeholder="V001"
          className={inputClass}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="make" className="text-sm font-medium text-[var(--ink)]">
            Make
          </label>
          <input id="make" name="make" type="text" placeholder="Toyota" className={inputClass} />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="vehicleModel" className="text-sm font-medium text-[var(--ink)]">
            Model
          </label>
          <input id="vehicleModel" name="vehicleModel" type="text" placeholder="Corolla" className={inputClass} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="year" className="text-sm font-medium text-[var(--ink)]">
            Year
          </label>
          <input id="year" name="year" type="number" min={1990} max={2030} placeholder="2020" className={inputClass} />
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="fuelType" className="text-sm font-medium text-[var(--ink)]">
            Fuel type
          </label>
          <select id="fuelType" name="fuelType" defaultValue="" className={inputClass}>
            <option value="">Unknown</option>
            <option value="petrol">Petrol</option>
            <option value="diesel">Diesel</option>
            <option value="hybrid">Hybrid</option>
            <option value="electric">Electric</option>
          </select>
        </div>
      </div>

      {state.error && (
        <p
          role="alert"
          className="rounded-[calc(var(--radius)*0.5)] bg-[var(--crit-soft)] px-3 py-2 text-sm text-[var(--crit)]"
        >
          {state.error}
        </p>
      )}

      <button
        type="submit"
        disabled={pending}
        className="mt-2 rounded-[calc(var(--radius)*0.5)] bg-[var(--accent)] px-4 py-2 font-medium text-[var(--accent-ink)] transition-opacity disabled:opacity-60"
      >
        {pending ? "Adding…" : "Add vehicle"}
      </button>
    </form>
  );
}
