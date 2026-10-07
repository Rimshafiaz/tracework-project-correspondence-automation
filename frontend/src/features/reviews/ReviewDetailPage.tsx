import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { getProjects } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import { approveProjectResolution, assignProjectResolution, getReview, rejectProjectResolution } from "../../api/reviews";
import type { DocumentRevisionReviewDetail, ProjectResolutionReviewDetail, RequirementReviewDetail, ReviewCorrespondence, ReviewProjectCandidate } from "../../api/types";
import { ErrorState } from "../../components/ErrorState";
import { TableLoading } from "../../components/LoadingState";
import { StatusBadge } from "../../components/StatusBadge";
import { formatDateOnly, formatDateTime, reviewTypeLabel } from "../../lib/format";
import { queryClient } from "../../lib/queryClient";

export function ReviewDetailPage() {
  const { reviewId = "" } = useParams();
  const review = useQuery({ queryKey: queryKeys.review(reviewId), queryFn: () => getReview(reviewId), enabled: Boolean(reviewId) });
  if (review.isPending) return <TableLoading rows={6} />;
  if (review.isError) {
    const missing = review.error instanceof ApiError && review.error.kind === "not_found";
    return <ErrorState title={missing ? "Review not found" : "Review could not be loaded"} message={missing ? "This review is not available." : "Stored review history could not be loaded."} onRetry={missing ? undefined : () => void review.refetch()} />;
  }
  if (review.data.review_type === "PROJECT_RESOLUTION") return <ProjectResolutionReview detail={review.data} />;
  if (review.data.review_type === "DOCUMENT_REVISION") return <DocumentRevisionReview detail={review.data} />;
  return <RequirementReview detail={review.data} />;
}

function ProjectResolutionReview({ detail }: { detail: ProjectResolutionReviewDetail }) {
  const navigate = useNavigate();
  const projects = useQuery({ queryKey: queryKeys.projects, queryFn: getProjects });
  const candidates = detail.detail.candidate_set.candidates;
  const [selected, setSelected] = useState<string[]>(detail.detail.preview.proposed_project_ids);
  const [isAssigning, setIsAssigning] = useState(false);
  const action = useMutation({
    mutationFn: async (kind: "approve" | "assign" | "reject") => {
      if (kind === "approve") return approveProjectResolution(detail.detail.review.review_item_id);
      if (kind === "reject") return rejectProjectResolution(detail.detail.review.review_item_id);
      return assignProjectResolution(detail.detail.review.review_item_id, selected);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.reviews });
      navigate("/reviews", { replace: true });
    },
  });
  const candidateMap = useMemo(() => new Map(candidates.map((candidate) => [candidate.project_id, candidate])), [candidates]);
  const evidenceLabels = useMemo(() => new Map(detail.detail.evidence.map((evidence, index) => [evidence.evidence_item_id, `E${index + 1}`])), [detail.detail.evidence]);

  return (
    <article className="review-detail">
      <Link className="back-link" to="/reviews">Reviews</Link>
      <header className="review-detail-header project-resolution-header"><div><h1>Project resolution</h1><span className="review-required-label">Review required</span></div><p>{detail.detail.preview.policy.reasons[0] ?? detail.detail.review.review_reason}</p></header>

      <ReviewSection title="Source">
        <div className="project-source-record">
          <CorrespondenceRecord correspondence={detail.detail.correspondence} />
          <EvidenceReferenceTable evidence={detail.detail.evidence} />
        </div>
      </ReviewSection>

      <ReviewSection title="Match">
        <div className="candidate-register"><div className="candidate-register-header"><span>Project</span><span>Evidence</span><span>Interpretation</span></div>
          {candidates.map((candidate) => <CandidateRecord candidate={candidate} evidenceLabels={evidenceLabels} interpretation={detail.detail.resolution.evidence.find((item) => item.project_id === candidate.project_id)?.interpretation} key={candidate.project_id} selected={detail.detail.preview.proposed_project_ids.includes(candidate.project_id)} />)}
        </div>
        {detail.detail.resolution.concerns.length ? <RecordList label="Concerns" values={detail.detail.resolution.concerns} /> : null}
        {detail.detail.resolution.conflicts.length ? <RecordList label="Conflicts" values={detail.detail.resolution.conflicts.map((item) => item.description)} /> : null}
      </ReviewSection>

      <ReviewSection title="Change">
        <h3>Authoritative project link</h3>
        <div className="change-register">
          <div><span>Current association</span><strong>{projectNames(detail.detail.preview.current_project_ids, candidateMap)}</strong></div>
          <span className="change-arrow" aria-hidden="true">→</span>
          <div><span>Proposed association</span><strong>{projectNames(detail.detail.preview.proposed_project_ids, candidateMap)}</strong></div>
        </div>
      </ReviewSection>

      <ReviewSection title="Decide">
        <div className="decision-copy"><RecordList label="Why review is required" values={detail.detail.preview.policy.reasons} />
          <p className="decision-policy technical-id">{detail.detail.preview.policy.policy_version}{detail.detail.preview.policy.triggered_rule_ids.length ? ` · ${detail.detail.preview.policy.triggered_rule_ids.join(" · ")}` : ""}</p>
          <p className="decision-help">Approving creates the project link. Assign / correct selects a different project. Reject leaves the correspondence unresolved.</p>
        </div>
        {isAssigning && detail.allowed_actions.includes("ASSIGN_OR_CORRECT") ? (
          <fieldset className="assignment-fieldset"><legend>Assignment for correction or manual assignment</legend>
            <div className="assignment-options">{(projects.data ?? []).map((project) => <label key={project.id}><input type="checkbox" checked={selected.includes(project.id)} onChange={() => setSelected((current) => current.includes(project.id) ? current.filter((id) => id !== project.id) : [...current, project.id])} /><span>{project.project_code}</span><span>{project.name}</span></label>)}</div>
            <div className="assignment-actions"><button className="text-button" type="button" onClick={() => setIsAssigning(false)}>Cancel assignment</button><button className="primary-button" type="button" disabled={action.isPending || selected.length === 0} onClick={() => action.mutate("assign")}>Save assignment</button></div>
          </fieldset>
        ) : null}
        {action.isError ? <p className="form-error" role="alert">{reviewActionError(action.error)}</p> : null}
        <div className="decision-actions">
          {detail.allowed_actions.includes("REJECT") ? <button className="danger-button" type="button" disabled={action.isPending} onClick={() => action.mutate("reject")}>Reject</button> : null}
          {detail.allowed_actions.includes("ASSIGN_OR_CORRECT") ? <button className="secondary-button" type="button" disabled={action.isPending} onClick={() => setIsAssigning(true)}>Assign / correct</button> : null}
          {detail.allowed_actions.includes("APPROVE") ? <button className="primary-button" type="button" disabled={action.isPending} onClick={() => action.mutate("approve")}>Approve</button> : null}
        </div>
      </ReviewSection>
    </article>
  );
}

function RequirementReview({ detail }: { detail: RequirementReviewDetail }) {
  const snapshots = new Map(detail.handoff.m11_snapshot.requirements.map((item) => [item.requirement_id, item]));
  const current = new Map(detail.handoff.current_requirements.map((item) => [item.requirement_id, item]));
  return (
    <article className="review-detail requirement-review-detail">
      <Link className="back-link" to="/reviews">Reviews</Link>
      <header className="requirement-review-heading">
        <div>
          <h1>Requirement review</h1>
          <p>Proposed change held for inspection. No authoritative update has been applied.</p>
        </div>
        <p>{reviewTypeLabel(detail.review_type)}<br />{formatDateTime(detail.review.created_at)}</p>
      </header>
      <div className="requirement-review-surface">
      <RequirementReviewSection title="Source"><RequirementCorrespondenceRecord correspondence={detail.correspondence} /></RequirementReviewSection>
      <RequirementReviewSection title="Requirement change">
        {detail.handoff.reconciliation.existing_impacts.map((impact) => {
          const observed = snapshots.get(impact.requirement_id);
          const now = current.get(impact.requirement_id);
          const currentState = now?.state ?? observed?.current_state ?? "REVIEW";
          const currentDate = now?.expected_date ?? observed?.expected_date ?? null;
          return <div className="requirement-impact-record" key={impact.requirement_id}><div className="requirement-impact-heading"><strong>{now?.name ?? observed?.name ?? "Requirement"}</strong><p>{impact.interpretation}</p></div><table className="comparison-table"><thead><tr><th>Field</th><th>Current</th><th>Proposed</th></tr></thead><tbody><tr><th>State</th><td><StatusBadge status={currentState} /></td><td><StatusBadge status={impact.proposed_state ?? currentState} /></td></tr>{(currentDate || impact.proposed_expected_date) ? <tr><th>Expected date</th><td>{formatDateOnly(currentDate)}</td><td>{formatDateOnly(impact.proposed_expected_date ?? currentDate)}</td></tr> : null}</tbody></table></div>;
        })}
        {detail.handoff.reconciliation.new_requirements.map((requirement, index) => <div className="new-requirement-record" key={`${requirement.name}-${index}`}><span className="metadata-label">New requirement proposal</span><strong>{requirement.name}</strong>{requirement.description ? <p>{requirement.description}</p> : null}<p>{requirement.interpretation}</p><small>Expected date: {formatDateOnly(requirement.expected_date)}</small></div>)}
      </RequirementReviewSection>
      <RequirementReviewSection title="Evidence"><RequirementEvidenceTable evidence={detail.handoff.evidence} /></RequirementReviewSection>
      <RequirementReviewSection title="Review basis">
        <dl className="review-basis-record"><div><dt>Decision</dt><dd>{detail.handoff.transition_preview.policy.decision}</dd></div><div><dt>Reason</dt><dd>{detail.handoff.transition_preview.policy.reasons.join(" ") || "No reason recorded"}</dd></div>{detail.handoff.reconciliation.concerns.map((item, index) => <div key={`concern-${index}`}><dt>Concern</dt><dd>{item.description}</dd></div>)}{detail.handoff.reconciliation.conflicts.map((item, index) => <div key={`conflict-${index}`}><dt>Conflict</dt><dd>{item.description}</dd></div>)}<div><dt>Technical definition</dt><dd><span className="technical-id">{detail.handoff.transition_preview.policy.policy_version}</span>{detail.handoff.transition_preview.policy.triggered_rule_ids.map((id) => <span className="technical-id" key={id}>{id}</span>)}</dd></div></dl>
      </RequirementReviewSection>
      </div>
    </article>
  );
}

function DocumentRevisionReview({ detail }: { detail: DocumentRevisionReviewDetail }) {
  const incoming = detail.incoming_document;
  return (
    <article className="review-detail requirement-review-detail">
      <Link className="back-link" to="/reviews">Reviews</Link>
      <header className="requirement-review-heading">
        <div>
          <h1>Document revision review</h1>
          <p>Revision state held for inspection. The current document has not been replaced.</p>
        </div>
        <p>{reviewTypeLabel(detail.review_type)}<br />{formatDateTime(detail.review.created_at)}</p>
      </header>
      <div className="requirement-review-surface">
        <RequirementReviewSection title="Source">
          <RequirementCorrespondenceRecord correspondence={detail.correspondence} />
          <dl className="review-basis-record">
            <div><dt>Attachment</dt><dd>{detail.attachment.filename}</dd></div>
            <div><dt>Media type</dt><dd>{detail.attachment.mime_type}</dd></div>
          </dl>
        </RequirementReviewSection>
        <RequirementReviewSection title="Document revision">
          <dl className="review-basis-record">
            <div><dt>Project</dt><dd>{incoming.project_code} {incoming.project_name}</dd></div>
            <div><dt>File</dt><dd>{incoming.filename}</dd></div>
            <div><dt>Category</dt><dd>{incoming.category}</dd></div>
            <div><dt>Document family</dt><dd>{incoming.document_family_key ?? "Not established"}</dd></div>
            <div><dt>Incoming revision</dt><dd>{incoming.revision_normalized ? `${incoming.revision_normalized}${incoming.revision_order === null ? "" : ` (order ${incoming.revision_order})`}` : incoming.revision_label ?? "Not established"}</dd></div>
            <div><dt>Incoming content hash</dt><dd><span className="technical-id">{incoming.content_hash}</span></dd></div>
            {detail.current_document ? <><div><dt>Current revision</dt><dd>{detail.current_document.revision_normalized}</dd></div><div><dt>Current content hash</dt><dd><span className="technical-id">{detail.current_document.content_hash}</span></dd></div></> : null}
          </dl>
        </RequirementReviewSection>
        <RequirementReviewSection title="Review basis">
          <dl className="review-basis-record">
            <div><dt>Outcome</dt><dd>Review required</dd></div>
            <div><dt>Reason</dt><dd>{detail.reasons.join(" ")}</dd></div>
            <div><dt>Transition</dt><dd>Previewed (review)</dd></div>
            <div><dt>Technical definition</dt><dd><span className="technical-id">{detail.policy_version}</span>{detail.triggered_rule_ids.map((id) => <span className="technical-id" key={id}>{id}</span>)}</dd></div>
          </dl>
        </RequirementReviewSection>
      </div>
    </article>
  );
}

function ReviewSection({ title, children }: { title: string; children: React.ReactNode }) { return <section className="review-record-section"><h2>{title}</h2>{children}</section>; }
function RequirementReviewSection({ title, children }: { title: string; children: React.ReactNode }) { return <section className="requirement-review-section"><h2>{title}</h2>{children}</section>; }
function CorrespondenceRecord({ correspondence }: { correspondence: ProjectResolutionReviewDetail["detail"]["correspondence"] }) { return <div className="correspondence-record"><dl><div><dt>From</dt><dd>{correspondence.sender_name ?? correspondence.sender_email ?? correspondence.sender_identifier}</dd></div><div><dt>Received</dt><dd>{formatDateTime(correspondence.received_at)}</dd></div><div><dt>Subject</dt><dd>{correspondence.subject ?? "No subject"}</dd></div></dl><p>{correspondence.body}</p></div>; }
function RequirementCorrespondenceRecord({ correspondence }: { correspondence: ReviewCorrespondence }) { return <div className="requirement-correspondence-record"><dl><div><dt>From</dt><dd>{correspondence.sender_name ?? correspondence.sender_email ?? correspondence.sender_identifier}</dd></div><div><dt>Subject</dt><dd>{correspondence.subject ?? "No subject"}</dd></div><div><dt>Received</dt><dd>{formatDateTime(correspondence.received_at)}</dd></div></dl><p>{correspondence.body}</p></div>; }
function EvidenceReferenceTable({ evidence }: { evidence: ProjectResolutionReviewDetail["detail"]["evidence"] }) { return evidence.length ? <div className="evidence-key"><h3>Evidence key</h3><ol>{evidence.map((item, index) => <li key={item.evidence_item_id}><span className="evidence-reference">E{index + 1}</span><div><strong>{humanizeSignalType(item.source_type)}</strong><blockquote>{item.excerpt}</blockquote>{item.page_number || item.section ? <small>{item.page_number ? `Page ${item.page_number}` : ""}{item.page_number && item.section ? ", " : ""}{item.section ?? ""}</small> : null}</div></li>)}</ol></div> : null; }
function RequirementEvidenceTable({ evidence }: { evidence: RequirementReviewDetail["handoff"]["evidence"] }) { return evidence.length ? <div className="requirement-evidence-table"><div className="requirement-evidence-header"><span>Source</span><span>Exact excerpt</span><span>Validity</span></div>{evidence.map((item) => <div className="requirement-evidence-row" key={item.evidence_item_id}><div>{humanizeSignalType(item.source_type)}{item.page_number || item.section ? <small>{item.page_number ? `Page ${item.page_number}` : ""}{item.page_number && item.section ? ", " : ""}{item.section ?? ""}</small> : null}</div><blockquote>{item.excerpt}</blockquote><strong>{item.validity}</strong></div>)}</div> : <p className="empty-state">No evidence excerpts are available.</p>; }
function CandidateRecord({ candidate, evidenceLabels, interpretation, selected }: { candidate: ReviewProjectCandidate; evidenceLabels: Map<string, string>; interpretation?: string; selected: boolean }) { return <div className="candidate-record"><div><span className="project-code">{candidate.project_code}</span><strong>{candidate.project_name}</strong></div><ul>{candidate.signals.map((signal, index) => <li key={`${signal.signal_type}-${index}`}>{signal.evidence_item_id && evidenceLabels.get(signal.evidence_item_id) ? <span className="evidence-reference">{evidenceLabels.get(signal.evidence_item_id)}</span> : null}<span>{humanizeSignalType(signal.signal_type)}: {signal.matched_value}</span></li>)}</ul><p><strong>{selected ? "Proposed." : "Alternative."}</strong> {interpretation ?? "No resolver interpretation recorded."}</p></div>; }
function humanizeSignalType(value: string) { return value.replaceAll("_", " ").toLowerCase().replace(/^./, (letter) => letter.toUpperCase()); }
function RecordList({ label, values }: { label: string; values: string[] }) { return <div className="record-list"><span className="metadata-label">{label}</span><ul>{values.map((value, index) => <li key={`${value}-${index}`}>{value}</li>)}</ul></div>; }
function projectLabel(candidate: ReviewProjectCandidate) { return `${candidate.project_code} ${candidate.project_name}`; }
function projectNames(ids: string[], candidates: Map<string, ReviewProjectCandidate>) { return ids.length ? ids.map((id) => candidates.get(id) ? projectLabel(candidates.get(id) as ReviewProjectCandidate) : id).join(", ") : "None"; }
function reviewActionError(error: Error) { return error instanceof ApiError && error.kind === "conflict" ? "This review has already been resolved or is no longer current." : "The review decision could not be saved."; }
