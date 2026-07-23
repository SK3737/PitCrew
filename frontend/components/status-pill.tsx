import type { ServiceStatus } from "@/lib/dal";
import { STATUS_COLOR_VAR, STATUS_LABEL, STATUS_SOFT_VAR } from "@/lib/format";

export function StatusPill({ status }: { status: ServiceStatus }) {
  const color = `var(${STATUS_COLOR_VAR[status]})`;
  const soft = `var(${STATUS_SOFT_VAR[status]})`;

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap"
      style={{ backgroundColor: soft, color }}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} />
      {STATUS_LABEL[status]}
    </span>
  );
}
