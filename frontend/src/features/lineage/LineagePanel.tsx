import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef } from "react";

import { ApiError } from "../../api/client";
import { getTransitionLineage } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import type { EvidenceLineage, JsonValue, LineageEvidence } from "../../api/types";
import { ErrorState } from "../../components/ErrorState";
import { formatDateOnly } from "../../lib/format";

export function LineagePanel({
  transitionId,
  onClose,
}: {
  transitionId: string;
  onClose: () => void;
}) {
  const lineage = useQuery({
    queryKey: queryKeys.transitionLineage(transitionId),
    queryFn: () => getTransitionLineage(transitionId),
  });

  return (
    <LineageDialog
      onClose={onClose}
      subtitle={lineage.data ? lineageSubtitle(lineage.data) : undefined}
    >
      {lineage.isPending ? <LineageLoading /> : null}
      {lineage.isError ? (
        <LineageError error={lineage.error} retry={() => void lineage.refetch()} />
      ) : null}
      {lineage.data ? <LineageContent lineage={lineage.data} /> : null}
    </LineageDialog>
  );
}

export function DevelopmentLineagePanel({
  lineage,
  onClose,
}: {
  lineage: EvidenceLineage;
  onClose: () => void;
}) {
  return (
    <LineageDialog onClose={onClose} subtitle={lineageSubtitle(lineage)}>
      <LineageContent lineage={lineage} />
    </LineageDialog>
  );
}

function LineageDialog({
  onClose,
  subtitle,
  children,
}: {
  onClose: () => void;
  subtitle?: string;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  return (
    <dialog
      className="lineage-dialog"
      ref={dialogRef}
      aria-labelledby="lineage-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="lineage-panel">
        <header className="lineage-header">
          <div>
            <h2 id="lineage-title">Evidence lineage</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          <button className="lineage-close-button" type="button" onClick={onClose} autoFocus>
            Close
          </button>
        </header>

        {children}
      </div>
    </dialog>
  );
}

function LineageContent({ lineage }: { lineage: EvidenceLineage }) {
  const attachments = new Map(lineage.attachments.map((item) => [item.id, item]));
  const outcomeItems: Array<[string, string]> = [
    ["Policy decision", displayValue(lineage.policy.decision)],
    ["Reason", lineage.policy.reasons.join(" ") || "No reason recorded"],
    ["Outcome", attributionLabel(lineage)],
  ];
  if (lineage.review) outcomeItems.push(["Review status", displayValue(lineage.review.status)]);
  return (
    <div className="lineage-content">
      {lineage.completeness === "LEGACY_PARTIAL" ? (
        <div className="lineage-notice">
          <strong>Historical record is incomplete.</strong>
          {lineage.completeness_notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      ) : null}

      <LineageSection title="Why this changed">
        <DefinitionList items={outcomeItems} />
      </LineageSection>

      <LineageSection title="At decision time">
        <DecisionState lineage={lineage} />
        <HistoricalEvidenceValidity evidence={lineage.evidence} />
      </LineageSection>

      <LineageSection title="Current state">
        <DefinitionList items={[
          ["Linked projects", String(lineage.current_state.linked_project_ids.length)],
        ]} />
        {lineage.current_state.requirements.length ? (
          <ul className="current-state-list">
            {lineage.current_state.requirements.map((requirement, index) => (
              <li key={requirement.requirement_id}>
                <span>{`Requirement ${index + 1}`}</span>
                <div className="current-requirement-value">
                  <strong>{requirement.exists ? requirement.state ?? "Unknown" : "Removed"}</strong>
                  {requirement.exists ? (
                    <span>Expected date: {formatDateOnly(requirement.expected_date)}</span>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="secondary-copy">No current requirement state is linked.</p>
        )}
        <CurrentEvidenceValidity evidence={lineage.evidence} />
      </LineageSection>

      <LineageSection title="Source evidence">
        <div className="correspondence-context">
          <p>
            <strong>{lineage.correspondence.subject ?? "No subject"}</strong>
          </p>
          <p>{lineage.correspondence.sender_identifier}</p>
        </div>
        {lineage.evidence.length ? (
          <ol className="evidence-list">
            {lineage.evidence.map((evidence, index) => {
              const attachment = evidence.attachment_id
                ? attachments.get(evidence.attachment_id)
                : undefined;
              return (
                <li className="evidence-item" key={evidence.id}>
                  <span className="evidence-reference">E{index + 1}</span>
                  <blockquote>{evidence.excerpt}</blockquote>
                  <p className="evidence-provenance">
                    {attachment?.filename ?? displayValue(evidence.source_type)}
                    {evidence.page_number ? `, page ${evidence.page_number}` : ""}
                    {evidence.section ? `, ${evidence.section}` : ""}
                  </p>
                  {evidence.invalidation_reason ? (
                    <p className="invalidation-note">
                      Current invalidation: {evidence.invalidation_reason}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="secondary-copy">No evidence excerpt is available.</p>
        )}
      </LineageSection>

      <details className="lineage-secondary-details">
        <summary>AI proposal</summary>
        <div className="lineage-secondary-content">
          <DefinitionList items={[
              ["Proposal type", lineage.proposal.proposal_type],
              ["Model", lineage.proposal.model_identifier],
              ["Prompt version", lineage.proposal.prompt_version],
            ]} />
          <h4>Structured proposal</h4>
          <pre>{JSON.stringify(lineage.proposal.structured_output, null, 2)}</pre>
        </div>
      </details>

      <details className="lineage-secondary-details">
        <summary>Policy technical detail</summary>
        <div className="lineage-secondary-content">
          <DefinitionList items={[
            ["Policy version", lineage.policy.policy_version],
            ["Decision", lineage.policy.decision],
          ]} />
          <h4>Rule identifiers</h4>
          <ul>
            {lineage.policy.triggered_rule_ids.map((rule) => (
              <li className="technical-id" key={rule}>{rule}</li>
            ))}
          </ul>
        </div>
      </details>
    </div>
  );
}

function LineageSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="lineage-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function DefinitionList({ items }: { items: Array<[string, string]> }) {
  return (
    <dl className="definition-list">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function DecisionState({ lineage }: { lineage: EvidenceLineage }) {
  if (lineage.transition.requirement_effects.length) {
    return <div className="decision-state-records">{lineage.transition.requirement_effects.map((effect, index) => (
      <div className="decision-state-record" key={effect.requirement_id}>
        {lineage.transition.requirement_effects.length > 1 ? <h4>{`Requirement ${index + 1}`}</h4> : null}
        <table className="comparison-table"><thead><tr><th>Field</th><th>Historical</th><th>Proposed</th></tr></thead><tbody>
          <tr><th>State</th><td>{effect.current_state}</td><td>{effect.proposed_state}</td></tr>
          {(effect.current_expected_date || effect.proposed_expected_date) ? <tr><th>Expected date</th><td>{formatDateOnly(effect.current_expected_date)}</td><td>{formatDateOnly(effect.proposed_expected_date)}</td></tr> : null}
          <tr><th>Transition</th><td colSpan={2}>{displayValue(lineage.transition.status)}</td></tr>
        </tbody></table>
      </div>
    ))}</div>;
  }
  const current = businessStateRows(lineage.transition.historical_current_state);
  const proposed = businessStateRows(lineage.transition.historical_proposed_state);
  const labels = Array.from(new Set([...current.keys(), ...proposed.keys()]));
  return <table className="comparison-table"><thead><tr><th>Field</th><th>Historical</th><th>Proposed</th></tr></thead><tbody>
    {labels.map((label) => <tr key={label}><th>{label}</th><td>{current.get(label) ?? "Not recorded"}</td><td>{proposed.get(label) ?? "Not recorded"}</td></tr>)}
    <tr><th>Transition</th><td colSpan={2}>{displayValue(lineage.transition.status)}</td></tr>
  </tbody></table>;
}

function businessStateRows(state: Record<string, JsonValue>): Map<string, string> {
  return new Map(Object.entries(state).map(([key, value]) => [humanizeKey(key), formatStateValue(key, value)]));
}

function humanizeKey(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function formatStateValue(key: string, value: JsonValue): string {
  if (value === null) return "Not set";
  if (Array.isArray(value)) {
    if (key.toLowerCase().includes("id")) return `${value.length} recorded`;
    return value.map((item) => formatStateValue(key, item)).join(", ");
  }
  if (typeof value === "object") return "Recorded state";
  if (key.toLowerCase().includes("id")) return "Recorded";
  if (typeof value === "string" && key.toLowerCase().includes("date")) return formatDateOnly(value);
  return String(value);
}

function HistoricalEvidenceValidity({ evidence }: { evidence: LineageEvidence[] }) {
  if (!evidence.length) return null;
  return (
    <ul className="validity-list historical-validity-list">
      {evidence.map((item) => (
        <li key={item.id}>
          <span>{displayValue(item.source_type)}</span>
          <dl className="validity-history">
            <div><dt>At proposal</dt><dd>{displayValue(item.validity_at_proposal)}</dd></div>
            <div><dt>At policy</dt><dd>{displayValue(item.validity_at_policy)}</dd></div>
            <div><dt>At outcome</dt><dd>{item.validity_at_outcome ? displayValue(item.validity_at_outcome) : "Not recorded"}</dd></div>
          </dl>
        </li>
      ))}
    </ul>
  );
}

function CurrentEvidenceValidity({ evidence }: { evidence: LineageEvidence[] }) {
  if (!evidence.length) return null;
  return (
    <ul className="validity-list">
      {evidence.map((item) => (
        <li key={item.id}>
          <span>{displayValue(item.source_type)}</span>
          <strong>{displayValue(item.current_validity)}</strong>
        </li>
      ))}
    </ul>
  );
}

function attributionLabel(lineage: EvidenceLineage): string {
  if (lineage.historical_outcome.attribution === "AUTOMATIC") return "Automatic";
  if (lineage.historical_outcome.authenticated_operator_subject) {
    return "Authenticated operator";
  }
  if (lineage.historical_outcome.operator_supplied_actor_label) {
    return `Historical operator: ${lineage.historical_outcome.operator_supplied_actor_label}`;
  }
  if (lineage.historical_outcome.attribution === "HUMAN") return "Human review";
  return "No final outcome recorded";
}

function lineageSubtitle(lineage: EvidenceLineage): string {
  const effect = lineage.transition.requirement_effects[0];
  if (effect) return `Requirement change: ${effect.current_state} to ${effect.proposed_state}`;
  const historicalState = stateValue(lineage.transition.historical_current_state);
  const proposedState = stateValue(lineage.transition.historical_proposed_state);
  if (historicalState && proposedState && historicalState !== proposedState) {
    return `Requirement change: ${historicalState} to ${proposedState}`;
  }
  return lineage.transition.affected_entity_type === "CORRESPONDENCE_PROJECT_LINK"
    ? "Project association change"
    : "Recorded state change";
}

const DISPLAY_VALUES: Record<string, string> = {
  ALLOW_AUTO_ACTION: "Allowed",
  REVIEW_REQUIRED: "Review required",
  REJECT_PROPOSAL: "Rejected",
  NO_MATCH: "No match",
  ATTACHMENT_TEXT: "Attachment text",
  BODY: "Message body",
  SUBJECT: "Subject",
  VALID: "Valid",
  INVALIDATED: "Invalidated",
  PENDING: "Pending",
  APPLIED: "Applied",
  REVIEW: "Review",
  REJECTED: "Rejected",
};

function displayValue(value: string): string {
  return DISPLAY_VALUES[value] ?? value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/^./, (letter) => letter.toUpperCase());
}

function stateValue(state: Record<string, JsonValue>): string | null {
  for (const key of ["requirement_state", "state"]) {
    const value = state[key];
    if (typeof value === "string" && value.length) return value;
  }
  return null;
}

function LineageLoading() {
  return (
    <div className="lineage-loading" aria-busy="true" aria-label="Loading evidence lineage">
      {Array.from({ length: 6 }, (_, index) => (
        <span className="loading-line" key={index} />
      ))}
    </div>
  );
}

export function LineageError({ error, retry }: { error: Error; retry: () => void }) {
  if (error instanceof ApiError && error.kind === "not_found") {
    return <ErrorState title="History not found" message="This transition is not available." />;
  }
  if (error instanceof ApiError && error.kind === "conflict") {
    return (
      <ErrorState
        title="History could not be loaded"
        message="Stored history could not be reconciled."
      />
    );
  }
  return (
    <ErrorState
      title="History could not be loaded"
      message="Tracework could not reach the API."
      onRetry={retry}
    />
  );
}
