export type ProjectStatus = "ACTIVE" | "CLOSED";
export type RequirementState = "OPEN" | "PARTIAL" | "SATISFIED" | "REVIEW";
export type EvidenceValidity = "VALID" | "INVALIDATED";
export type LineageAttribution = "AUTOMATIC" | "HUMAN" | "NONE";

export interface ProjectSummary {
  id: string;
  project_code: string;
  name: string;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export interface ProjectIdentifier {
  id: string;
  identifier_type: string;
  display_value: string;
  verified: boolean;
}

export interface ProjectRequirement {
  id: string;
  name: string;
  description: string | null;
  state: RequirementState;
  expected_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectContact {
  id: string;
  email: string;
  display_name: string;
  role: string | null;
  is_active: boolean;
}

export interface ProjectWorkspace {
  project: ProjectSummary;
  identifiers: ProjectIdentifier[];
  contacts: ProjectContact[];
  requirements: ProjectRequirement[];
}

export type ReplyDraftStatus = "GENERATED" | "APPROVED" | "REJECTED" | "SEND_PENDING" | "RETRYABLE_FAILURE" | "SENT";
export type ReplyType = "ACKNOWLEDGEMENT" | "CLARIFICATION_REQUEST" | "OVERDUE_FOLLOW_UP";

export interface ReplyDraftContent { subject: string; body: string; }
export interface ReplyDraft {
  id: string;
  follow_up_id: string;
  project_id: string;
  requirement_id: string;
  ai_proposal_id: string | null;
  source_correspondence_event_id: string | null;
  target_correspondence_event_id: string | null;
  project_contact_id: string | null;
  reply_type: ReplyType;
  generated: ReplyDraftContent;
  edited: ReplyDraftContent | null;
  effective: ReplyDraftContent;
  status: ReplyDraftStatus;
  recipient_email: string | null;
  gmail_thread_id: string | null;
  source_gmail_message_id: string | null;
  approved_at: string | null;
  approved_by_subject: string | null;
  rejected_at: string | null;
  send_attempt_id: string | null;
  send_attempted_at: string | null;
  send_failure_code: string | null;
  sent_at: string | null;
  gmail_message_id: string | null;
  gmail_sent_thread_id: string | null;
  can_edit: boolean;
  can_approve: boolean;
  can_reject: boolean;
  can_send: boolean;
  can_retry_send: boolean;
  send_attention_required: boolean;
  generated_at: string;
  created_at: string;
  updated_at: string;
}

export type ReplyDraftSendStatus = "SENT_NOW" | "RECONCILED_SENT" | "ALREADY_SENT" | "SEND_STILL_PENDING" | "RETRYABLE_FAILURE" | "AMBIGUOUS_RECOVERY" | "ACTION_REQUIRED";
export interface ReplyDraftSendResult { status: ReplyDraftSendStatus; reply_draft_id: string; gmail_message_id: string | null; gmail_thread_id: string | null; failure_code: string | null; }

export interface ProjectSetupIdentifierInput {
  identifier_type: string;
  display_value: string;
}

export interface ProjectSetupContactInput {
  email: string;
  display_name: string;
  role?: string | null;
}

export interface ProjectSetupRequirementInput {
  name: string;
  description?: string | null;
  expected_date?: string | null;
}

export interface ProjectSetupRequest {
  name: string;
  identifiers: ProjectSetupIdentifierInput[];
  contacts: ProjectSetupContactInput[];
  requirements: ProjectSetupRequirementInput[];
}

export type ReviewType =
  | "PROJECT_RESOLUTION"
  | "REQUIREMENT_CHANGE"
  | "NEW_REQUIREMENT"
  | "DOCUMENT_REVISION";
export type ReviewStatus = "PENDING" | "APPROVED" | "CORRECTED" | "REJECTED";
export type ReviewAllowedAction = "APPROVE" | "ASSIGN_OR_CORRECT" | "REJECT";

export interface ReviewQueueSummary {
  review_item_id: string;
  correspondence_event_id: string;
  review_type: ReviewType;
  status: ReviewStatus;
  review_reason: string;
  created_at: string;
  resolved_at: string | null;
  allowed_actions: ReviewAllowedAction[];
}

export interface ReviewCorrespondence {
  correspondence_event_id: string;
  source: string;
  sender_identifier: string;
  sender_email: string | null;
  sender_name: string | null;
  subject: string | null;
  body: string;
  received_at: string;
}

export interface CandidateSignal {
  signal_type: string;
  matched_value: string;
  source: string;
  identifier_type: string | null;
  evidence_item_id?: string | null;
  exact: boolean;
  verified: boolean;
  previously_approved: boolean;
}

export interface ReviewProjectCandidate {
  project_id: string;
  project_code: string;
  project_name: string;
  project_status: ProjectStatus;
  signals: CandidateSignal[];
}

export interface PolicySnapshot {
  policy_version: string;
  decision: string;
  triggered_rule_ids: string[];
  reasons: string[];
}

export interface ProjectResolutionReviewDetail {
  review_type: "PROJECT_RESOLUTION";
  allowed_actions: ReviewAllowedAction[];
  detail: {
    review: Omit<ReviewQueueSummary, "review_type" | "allowed_actions">;
    state_transition_id: string;
    proposal_id: string;
    policy_evaluation_id: string;
    correspondence: ReviewCorrespondence;
    preview: {
      resolver_status: string;
      current_project_ids: string[];
      proposed_project_ids: string[];
      alternative_project_ids: string[];
      valid_evidence_ids: string[];
      invalidated_evidence_ids: string[];
      policy: PolicySnapshot;
      disposition: string;
      requires_manual_project_assignment: boolean;
    };
    candidate_set: { candidates: ReviewProjectCandidate[] };
    resolution: {
      status: string;
      project_ids: string[];
      evidence: Array<{ project_id: string; interpretation: string }>;
      conflicts: Array<{ description: string }>;
      concerns: string[];
    };
    evidence: Array<{
      evidence_item_id: string;
      attachment_id: string | null;
      source_type: string;
      page_number: number | null;
      section: string | null;
      excerpt: string;
      validity: EvidenceValidity;
      invalidation_reason: string | null;
    }>;
  };
}

export interface RequirementReviewDetail {
  review_type: "REQUIREMENT_CHANGE" | "NEW_REQUIREMENT";
  allowed_actions: ReviewAllowedAction[];
  review: ReviewQueueSummary;
  correspondence: ReviewCorrespondence;
  handoff: {
    project_id: string;
    state_transition_id: string;
    reconciliation: {
      existing_impacts: Array<{
        requirement_id: string;
        disposition: "NO_CHANGE" | "UPDATE_PROPOSED";
        proposed_state: RequirementState | null;
        proposed_expected_date: string | null;
        interpretation: string;
      }>;
      new_requirements: Array<{
        name: string;
        description: string | null;
        expected_date: string | null;
        interpretation: string;
      }>;
      concerns: Array<{ concern_type: string; description: string }>;
      conflicts: Array<{ description: string }>;
    };
    m11_snapshot: {
      requirements: Array<{
        requirement_id: string;
        name: string;
        description: string | null;
        current_state: RequirementState;
        expected_date: string | null;
      }>;
    };
    current_requirements: Array<{
      requirement_id: string;
      name: string;
      description: string | null;
      state: RequirementState;
      expected_date: string | null;
    }>;
    transition_preview: {
      policy: PolicySnapshot;
      disposition: string;
      requirement_effects: RequirementTransitionEffect[];
    };
    evidence: Array<{
      evidence_item_id: string;
      requirement_id: string | null;
      source_type: string;
      page_number: number | null;
      section: string | null;
      excerpt: string;
      validity: EvidenceValidity;
      invalidation_reason: string | null;
    }>;
  };
}

export interface DocumentRevisionReviewDetail {
  review_type: "DOCUMENT_REVISION";
  allowed_actions: [];
  review: ReviewQueueSummary;
  correspondence: ReviewCorrespondence;
  attachment: {
    attachment_id: string;
    filename: string;
    mime_type: string;
    content_hash: string | null;
  };
  state_transition_id: string;
  transition_status: "PREVIEWED";
  disposition: "REVIEW";
  incoming_document: {
    document_id: string;
    source_attachment_id: string;
    filename: string;
    project_id: string;
    project_code: string;
    project_name: string;
    category: string;
    document_family_key: string | null;
    revision_label: string | null;
    revision_normalized: string | null;
    revision_order: number | null;
    content_hash: string;
  };
  current_document: {
    document_id: string;
    revision_normalized: string;
    revision_order: number;
    content_hash: string;
  } | null;
  outcome: "REVIEW_REQUIRED";
  reasons: string[];
  policy_version: "document-revision/1";
  triggered_rule_ids: string[];
}

export type ReviewReadDetail =
  | ProjectResolutionReviewDetail
  | RequirementReviewDetail
  | DocumentRevisionReviewDetail;

export interface ReviewDecisionResponse {
  review_item_id: string;
  status: ReviewStatus;
  action: string;
  project_ids: string[];
  project_link_ids: string[];
  idempotent_replay: boolean;
}

export interface RequirementReviewDecisionResponse {
  review_item_id: string;
  status: ReviewStatus;
  action: "APPROVE" | "REJECT";
  applied_requirement_ids: string[];
  follow_up_ids: string[];
  idempotent_replay: boolean;
}

export type ProjectActivityType =
  | "CORRESPONDENCE_LINKED"
  | "PROJECT_RESOLUTION_REVIEW_CREATED"
  | "PROJECT_RESOLUTION_REVIEW_RESOLVED"
  | "REQUIREMENT_CHANGE_PROPOSED"
  | "REQUIREMENT_CHANGE_APPLIED"
  | "REQUIREMENT_REVIEW_CREATED"
  | "REQUIREMENT_REVIEW_APPROVED"
  | "REQUIREMENT_REVIEW_REJECTED"
  | "DOCUMENT_FILED"
  | "DOCUMENT_REVISION_SELECTED_CURRENT"
  | "DOCUMENT_REVISION_RETAINED_HISTORICAL"
  | "DOCUMENT_REVISION_DUPLICATE_RECORDED"
  | "DOCUMENT_REVISION_REVIEW_CREATED";

export interface ProjectActivityEvent {
  event_id: string;
  event_type: ProjectActivityType;
  occurred_at: string;
  project_id: string;
  correspondence_event_id: string | null;
  requirement_id: string | null;
  summary: string;
  attribution: LineageAttribution;
  authenticated_operator_subject: string | null;
  operator_supplied_actor_label: string | null;
  proposal_id: string | null;
  policy_evaluation_id: string | null;
  state_transition_id: string | null;
  review_item_id: string | null;
}

export interface ProjectActivity {
  project_id: string;
  events: ProjectActivityEvent[];
}

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface LineageCorrespondence {
  id: string;
  source: string;
  sender_identifier: string;
  subject: string | null;
  body: string;
  received_at: string;
}

export interface LineageAttachment {
  id: string;
  filename: string;
  mime_type: string;
  content_hash: string | null;
}

export interface LineageEvidence {
  id: string;
  correspondence_event_id: string;
  attachment_id: string | null;
  project_id: string | null;
  requirement_id: string | null;
  source_type: string;
  excerpt: string;
  start_offset: number | null;
  end_offset: number | null;
  page_number: number | null;
  section: string | null;
  validity_at_proposal: EvidenceValidity;
  validity_at_policy: EvidenceValidity;
  validity_at_outcome: EvidenceValidity | null;
  current_validity: EvidenceValidity;
  invalidated_at: string | null;
  invalidation_reason: string | null;
  linked_to_proposal: boolean;
  linked_to_policy: boolean;
  linked_to_transition: boolean;
}

export interface LineageProposal {
  id: string;
  proposal_type: string;
  model_identifier: string;
  prompt_version: string;
  input_hash: string;
  structured_output: Record<string, JsonValue>;
  created_at: string;
}

export interface LineagePolicy {
  id: string;
  policy_version: string;
  decision: string;
  triggered_rule_ids: string[];
  reasons: string[];
  evaluated_at: string;
}

export interface RequirementTransitionEffect {
  requirement_id: string;
  observed_state: RequirementState;
  observed_expected_date: string | null;
  current_state: RequirementState;
  current_expected_date: string | null;
  proposed_state: RequirementState;
  proposed_expected_date: string | null;
  decision: string;
  triggered_rule_ids: string[];
  reasons: string[];
  evidence_ids: string[];
}

export interface LineageTransition {
  id: string;
  affected_entity_type: string;
  affected_entity_id: string;
  historical_current_state: Record<string, JsonValue>;
  historical_proposed_state: Record<string, JsonValue>;
  requirement_effects: RequirementTransitionEffect[];
  disposition: string;
  status: string;
  created_at: string;
  applied_at: string | null;
}

export interface LineageReview {
  id: string;
  review_type: string;
  status: string;
  review_reason: string;
  correction_payload: Record<string, JsonValue> | null;
  created_at: string;
  resolved_at: string | null;
}

export interface CurrentRequirementState {
  requirement_id: string;
  exists: boolean;
  project_id: string | null;
  state: RequirementState | null;
  expected_date: string | null;
}

export interface EvidenceLineage {
  completeness: "COMPLETE" | "LEGACY_PARTIAL";
  completeness_notes: string[];
  correspondence: LineageCorrespondence;
  attachments: LineageAttachment[];
  evidence: LineageEvidence[];
  proposal: LineageProposal;
  policy: LineagePolicy;
  transition: LineageTransition;
  review: LineageReview | null;
  audit_events: Array<{
    id: string;
    event_type: string;
    actor_type: string;
    authenticated_operator_subject: string | null;
    operator_supplied_actor_label: string | null;
    details: Record<string, JsonValue>;
    occurred_at: string;
  }>;
  historical_outcome: {
    attribution: LineageAttribution;
    occurred_at: string | null;
    authenticated_operator_subject: string | null;
    operator_supplied_actor_label: string | null;
  };
  current_state: {
    linked_project_ids: string[];
    requirements: CurrentRequirementState[];
  };
}
