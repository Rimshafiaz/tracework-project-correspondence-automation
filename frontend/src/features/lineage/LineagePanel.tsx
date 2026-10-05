import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef } from "react";

import { ApiError } from "../../api/client";
import { getTransitionLineage } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import type { EvidenceLineage, JsonValue, LineageEvidence } from "../../api/types";
import { ErrorState } from "../../components/ErrorState";
import { formatDateOnly, formatDateTime } from "../../lib/format";

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
    <LineageDialog onClose={onClose}>
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
    <LineageDialog onClose={onClose}>
      <LineageContent lineage={lineage} />
    </LineageDialog>
  );
}

function LineageDialog({ onClose, children }: { onClose: () => void; children: ReactNode }) {
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
          <h2 id="lineage-title">Evidence lineage</h2>
          <button className="text-button" type="button" onClick={onClose} autoFocus>
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
    ["Policy decision", lineage.policy.decision],
    ["Outcome", attributionLabel(lineage)],
    [
      "Recorded",
      lineage.historical_outcome.occurred_at
        ? formatDateTime(lineage.historical_outcome.occurred_at)
        : "Not recorded",
    ],
  ];
  if (lineage.review) outcomeItems.push(["Review status", lineage.review.status]);
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
        <ReasonList reasons={lineage.policy.reasons} />
      </LineageSection>

      <LineageSection title="At decision time">
        <StateComparison
          current={lineage.transition.historical_current_state}
          proposed={lineage.transition.historical_proposed_state}
        />
        <p className="section-metadata">
          Transition status: {lineage.transition.status}
        </p>
        <HistoricalEvidenceValidity evidence={lineage.evidence} />
      </LineageSection>

      <LineageSection title="Current state">
        {lineage.current_state.linked_project_ids.length ? (
          <div className="current-project-links">
            <h4>Linked projects</h4>
            <ul>
              {lineage.current_state.linked_project_ids.map((projectId) => (
                <li className="technical-id" key={projectId}>{projectId}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {lineage.current_state.requirements.length ? (
          <ul className="current-state-list">
            {lineage.current_state.requirements.map((requirement) => (
              <li key={requirement.requirement_id}>
                <span className="technical-id">{requirement.requirement_id}</span>
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
          <ul className="evidence-list">
            {lineage.evidence.map((evidence) => {
              const attachment = evidence.attachment_id
                ? attachments.get(evidence.attachment_id)
                : undefined;
              return (
                <li className="evidence-item" key={evidence.id}>
                  <blockquote>{evidence.excerpt}</blockquote>
                  <p className="evidence-provenance">
                    {attachment?.filename ?? evidence.source_type}
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
          </ul>
        ) : (
          <p className="secondary-copy">No evidence excerpt is available.</p>
        )}
      </LineageSection>

      <LineageSection title="AI proposal">
        <DefinitionList
          items={[
            ["Proposal type", lineage.proposal.proposal_type],
            ["Model", lineage.proposal.model_identifier],
            ["Prompt version", lineage.proposal.prompt_version],
          ]}
        />
        <details className="technical-details">
          <summary>Structured proposal</summary>
          <pre>{JSON.stringify(lineage.proposal.structured_output, null, 2)}</pre>
        </details>
      </LineageSection>

      <LineageSection title="Policy details">
        <DefinitionList
          items={[
            ["Policy version", lineage.policy.policy_version],
            ["Decision", lineage.policy.decision],
          ]}
        />
        <ReasonList reasons={lineage.policy.reasons} />
        <details className="technical-details">
          <summary>Rule identifiers</summary>
          <ul>
            {lineage.policy.triggered_rule_ids.map((rule) => (
              <li className="technical-id" key={rule}>{rule}</li>
            ))}
          </ul>
        </details>
      </LineageSection>
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

function ReasonList({ reasons }: { reasons: string[] }) {
  if (!reasons.length) return null;
  return <ul className="reason-list">{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>;
}

function StateComparison({
  current,
  proposed,
}: {
  current: Record<string, JsonValue>;
  proposed: Record<string, JsonValue>;
}) {
  return (
    <div className="state-comparison">
      <div>
        <h4>Observed</h4>
        <pre>{JSON.stringify(current, null, 2)}</pre>
      </div>
      <div>
        <h4>Proposed</h4>
        <pre>{JSON.stringify(proposed, null, 2)}</pre>
      </div>
    </div>
  );
}

function HistoricalEvidenceValidity({ evidence }: { evidence: LineageEvidence[] }) {
  if (!evidence.length) return null;
  return (
    <ul className="validity-list historical-validity-list">
      {evidence.map((item) => (
        <li key={item.id}>
          <span>{item.source_type}</span>
          <dl className="validity-history">
            <div><dt>At proposal</dt><dd>{item.validity_at_proposal}</dd></div>
            <div><dt>At policy</dt><dd>{item.validity_at_policy}</dd></div>
            <div><dt>At outcome</dt><dd>{item.validity_at_outcome ?? "Not recorded"}</dd></div>
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
          <span>{item.source_type}</span>
          <strong>{item.current_validity}</strong>
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
