import type {
  EvidenceLineage,
  ProjectActivity,
  ProjectActivityEvent,
  ProjectSummary,
  ProjectWorkspace,
} from "../api/types";

export const project: ProjectSummary = {
  id: "project-1",
  project_code: "TW-101",
  name: "Release Controls",
  status: "ACTIVE",
  created_at: "2026-09-01T09:00:00Z",
  updated_at: "2026-10-01T09:00:00Z",
};

export const workspace: ProjectWorkspace = {
  project,
  contacts: [],
  identifiers: [
    {
      id: "identifier-1",
      identifier_type: "repository_url",
      display_value: "https://example.test/release-controls",
      verified: true,
    },
    {
      id: "identifier-2",
      identifier_type: "alias",
      display_value: "Unverified alias",
      verified: false,
    },
  ],
  requirements: [
    {
      id: "requirement-1",
      name: "Security review",
      description: "Confirm the final review evidence.",
      state: "PARTIAL",
      expected_date: "2026-10-05",
      created_at: "2026-09-02T09:00:00Z",
      updated_at: "2026-10-02T09:00:00Z",
    },
  ],
};

export const transitionActivity: ProjectActivityEvent = {
  event_id: "event-1",
  event_type: "REQUIREMENT_CHANGE_APPLIED",
  occurred_at: "2026-10-03T10:00:00Z",
  project_id: project.id,
  correspondence_event_id: "correspondence-1",
  requirement_id: "requirement-1",
  summary: 'Requirement "Security review" moved OPEN to PARTIAL',
  attribution: "AUTOMATIC",
  authenticated_operator_subject: null,
  operator_supplied_actor_label: null,
  proposal_id: "proposal-1",
  policy_evaluation_id: "policy-1",
  state_transition_id: "transition-1",
  review_item_id: null,
};

export const linkedActivity: ProjectActivityEvent = {
  ...transitionActivity,
  event_id: "event-2",
  event_type: "CORRESPONDENCE_LINKED",
  occurred_at: "2026-10-02T10:00:00Z",
  summary: "Correspondence linked to this project",
  attribution: "HUMAN",
  authenticated_operator_subject: "operator-subject",
  state_transition_id: null,
};

export const activity: ProjectActivity = {
  project_id: project.id,
  events: [transitionActivity, linkedActivity],
};

export const lineage: EvidenceLineage = {
  completeness: "COMPLETE",
  completeness_notes: [],
  correspondence: {
    id: "correspondence-1",
    source: "gmail",
    sender_identifier: "sender@example.test",
    subject: "Security review update",
    body: "The review is partly complete.",
    received_at: "2026-10-03T09:00:00Z",
  },
  attachments: [
    {
      id: "attachment-1",
      filename: "review.pdf",
      mime_type: "application/pdf",
      content_hash: "hash",
    },
  ],
  evidence: [
    {
      id: "evidence-1",
      correspondence_event_id: "correspondence-1",
      attachment_id: "attachment-1",
      project_id: project.id,
      requirement_id: "requirement-1",
      source_type: "ATTACHMENT_TEXT",
      excerpt: "The review is partly complete.",
      start_offset: 0,
      end_offset: 30,
      page_number: 2,
      section: null,
      validity_at_proposal: "VALID",
      validity_at_policy: "VALID",
      validity_at_outcome: "VALID",
      current_validity: "INVALIDATED",
      invalidated_at: "2026-10-04T09:00:00Z",
      invalidation_reason: "The sender withdrew the attachment.",
      linked_to_proposal: true,
      linked_to_policy: true,
      linked_to_transition: true,
    },
  ],
  proposal: {
    id: "proposal-1",
    proposal_type: "REQUIREMENT_RECONCILIATION",
    model_identifier: "test-model",
    prompt_version: "requirement-reconciler/1",
    input_hash: "input-hash",
    structured_output: { status: "UPDATE_PROPOSED" },
    created_at: "2026-10-03T09:10:00Z",
  },
  policy: {
    id: "policy-1",
    policy_version: "requirement-policy/1",
    decision: "ALLOW_AUTO_ACTION",
    triggered_rule_ids: ["RID-300-OPEN-TO-PARTIAL"],
    reasons: ["The proposed change has valid requirement-scoped evidence."],
    evaluated_at: "2026-10-03T09:12:00Z",
  },
  transition: {
    id: "transition-1",
    affected_entity_type: "REQUIREMENT_BUNDLE",
    affected_entity_id: "proposal-1",
    historical_current_state: { requirement_state: "OPEN" },
    historical_proposed_state: { requirement_state: "PARTIAL" },
    requirement_effects: [
      {
        requirement_id: "requirement-1",
        observed_state: "OPEN",
        observed_expected_date: null,
        current_state: "OPEN",
        current_expected_date: null,
        proposed_state: "PARTIAL",
        proposed_expected_date: null,
        decision: "ALLOW_AUTO_ACTION",
        triggered_rule_ids: ["RID-300-OPEN-TO-PARTIAL"],
        reasons: ["The proposed change has valid requirement-scoped evidence."],
        evidence_ids: ["evidence-1"],
      },
    ],
    disposition: "AUTO_APPLY",
    status: "APPLIED",
    created_at: "2026-10-03T09:12:00Z",
    applied_at: "2026-10-03T09:12:00Z",
  },
  review: null,
  audit_events: [],
  historical_outcome: {
    attribution: "AUTOMATIC",
    occurred_at: "2026-10-03T09:12:00Z",
    authenticated_operator_subject: null,
    operator_supplied_actor_label: null,
  },
  current_state: {
    linked_project_ids: [project.id],
    requirements: [
      {
        requirement_id: "requirement-1",
        exists: true,
        project_id: project.id,
        state: "SATISFIED",
        expected_date: null,
      },
    ],
  },
};
