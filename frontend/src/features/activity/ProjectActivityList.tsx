import type { ProjectActivityEvent } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { formatDateTime } from "../../lib/format";

export function ProjectActivityList({
  events,
  onViewEvidence,
}: {
  events: ProjectActivityEvent[];
  onViewEvidence: (transitionId: string) => void;
}) {
  if (events.length === 0) {
    return <EmptyState message="No project activity has been recorded yet." />;
  }

  return (
    <ol className="activity-list">
      {events.map((event) => (
        <li className="activity-item" key={event.event_id}>
          <div className="activity-content">
            <p className="activity-summary">{event.summary}</p>
            <div className="activity-metadata">
              <time dateTime={event.occurred_at}>
                {formatDateTime(event.occurred_at)}
              </time>
              <span>{attributionLabel(event)}</span>
            </div>
          </div>
          {event.state_transition_id ? (
            <button
              className="text-button activity-action"
              type="button"
              onClick={() => onViewEvidence(event.state_transition_id as string)}
            >
              View evidence
            </button>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function attributionLabel(event: ProjectActivityEvent): string {
  if (event.attribution === "AUTOMATIC") return "Automatic";
  if (event.authenticated_operator_subject) return "Authenticated operator";
  if (event.operator_supplied_actor_label) {
    return `Historical operator: ${event.operator_supplied_actor_label}`;
  }
  if (event.attribution === "HUMAN") return "Human review";
  return "Recorded event";
}
