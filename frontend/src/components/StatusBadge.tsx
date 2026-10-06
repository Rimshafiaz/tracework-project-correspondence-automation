import type { ProjectStatus, RequirementState } from "../api/types";

export function StatusBadge({
  status,
}: {
  status: ProjectStatus | RequirementState;
}) {
  const label = status === "ACTIVE" || status === "CLOSED"
    ? `${status[0]}${status.slice(1).toLowerCase()}`
    : status;
  return <span className={`status status-${status.toLowerCase()}`}>{label}</span>;
}
