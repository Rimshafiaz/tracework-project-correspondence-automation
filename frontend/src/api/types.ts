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

export interface ProjectWorkspace {
  project: ProjectSummary;
  identifiers: ProjectIdentifier[];
  requirements: ProjectRequirement[];
}

export type ProjectActivityType =
  | "CORRESPONDENCE_LINKED"
  | "PROJECT_RESOLUTION_REVIEW_CREATED"
  | "PROJECT_RESOLUTION_REVIEW_RESOLVED"
  | "REQUIREMENT_CHANGE_PROPOSED"
  | "REQUIREMENT_CHANGE_APPLIED"
  | "REQUIREMENT_REVIEW_CREATED";

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
