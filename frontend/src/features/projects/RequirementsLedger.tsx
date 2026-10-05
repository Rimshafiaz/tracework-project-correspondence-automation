import type { ProjectRequirement } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateOnly } from "../../lib/format";

export function RequirementsLedger({
  requirements,
}: {
  requirements: ProjectRequirement[];
}) {
  return (
    <section className="workspace-section" aria-labelledby="requirements-title">
      <div className="section-heading-row">
        <h2 id="requirements-title">Requirements</h2>
      </div>
      {requirements.length === 0 ? (
        <EmptyState message="No requirements are currently recorded for this project." />
      ) : (
        <div className="data-table requirement-table">
          <div className="data-table-header" aria-hidden="true">
            <span>Requirement</span>
            <span>State</span>
            <span>Expected date</span>
          </div>
          <ul className="data-table-body">
            {requirements.map((requirement) => (
              <li className="requirement-row" key={requirement.id}>
                <div className="requirement-main">
                  <p className="requirement-name">{requirement.name}</p>
                  {requirement.description ? (
                    <p className="requirement-description">
                      {requirement.description}
                    </p>
                  ) : null}
                </div>
                <div className="requirement-field" data-label="State">
                  <StatusBadge status={requirement.state} />
                </div>
                <div className="requirement-date" data-label="Expected date">
                  {formatDateOnly(requirement.expected_date)}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
