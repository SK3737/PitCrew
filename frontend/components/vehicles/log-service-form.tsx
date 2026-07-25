"use client";

import { useActionState } from "react";

import { logServiceAction, type LogServiceFormState } from "@/app/dashboard/vehicles/[id]/service/actions";

const initialState: LogServiceFormState = {};

const inputClass =
  "rounded-[calc(var(--radius)*0.5)] border border-[var(--border-strong)] bg-[var(--surface-2)] px-3 py-2 text-[var(--ink)] outline-none focus-visible:border-[var(--accent)]";

export function LogServiceForm({ vehicleId }: { vehicleId: string }) {
  const boundAction = logServiceAction.bind(null, vehicleId);
  const [state, action, pending] = useActionState(boundAction, initialState);

  return (
    <form action={action} className="mt-6 flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="serviceDate" className="text-sm font-medium text-[var(--ink)]">
          Service date
        </label>
        <input id="serviceDate" name="serviceDate" type="date" required className={inputClass} />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="odometerKm" className="text-sm font-medium text-[var(--ink)]">
          Odometer (km)
        </label>
        <input id="odometerKm" name="odometerKm" type="number" min={0} step="1" required placeholder="45000" className={inputClass} />
      </div>

      <div className="flex flex-col gap-1.5">
        <label htmlFor="serviceType" className="text-sm font-medium text-[var(--ink)]">
          Service type
        </label>
        <select id="serviceType" name="serviceType" defaultValue="" className={inputClass}>
          <option value="">Unspecified</option>
          <option value="oil_change">Oil change</option>
          <option value="full_service">Full service</option>
          <option value="inspection">Inspection</option>
          <option value="brake_service">Brake service</option>
        </select>
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
        {pending ? "Saving…" : "Log service"}
      </button>
    </form>
  );
}
