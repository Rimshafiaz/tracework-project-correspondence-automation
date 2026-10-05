import type { ProjectStatus, RequirementState } from "../api/types";

export function StatusBadge({
  status,
}: {
  status: ProjectStatus | RequirementState;
}) {
  return <span className={`status status-${status.toLowerCase()}`}>{status}</span>;
}
