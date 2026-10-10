import type { ProjectStatus, ReplyDraftStatus, RequirementState } from "../api/types";
import { formatLabel } from "../lib/format";

export function StatusBadge({
  status,
}: {
  status: ProjectStatus | RequirementState | ReplyDraftStatus;
}) {
  return <span className={`status status-${status.toLowerCase()}`}>{formatLabel(status)}</span>;
}
