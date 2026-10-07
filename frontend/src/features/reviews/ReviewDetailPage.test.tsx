import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getReview: vi.fn(),
  getProjects: vi.fn(),
  approveProjectResolution: vi.fn(),
  assignProjectResolution: vi.fn(),
  rejectProjectResolution: vi.fn(),
}));

vi.mock("../../api/reviews", () => ({
  getReview: api.getReview,
  approveProjectResolution: api.approveProjectResolution,
  assignProjectResolution: api.assignProjectResolution,
  rejectProjectResolution: api.rejectProjectResolution,
}));
vi.mock("../../api/projects", () => ({ getProjects: api.getProjects }));

import { renderWithProviders } from "../../test/render";
import { ReviewDetailPage } from "./ReviewDetailPage";

const correspondence = {
  correspondence_event_id: "correspondence-1",
  source: "gmail",
  sender_identifier: "sender@example.test",
  sender_email: "sender@example.test",
  sender_name: "Sender",
  subject: "Requirement update",
  body: "The review is partly complete.",
  received_at: "2026-10-05T09:00:00Z",
};

function renderPage() {
  return renderWithProviders(
    <Routes><Route path="/reviews/:reviewId" element={<ReviewDetailPage />} /></Routes>,
    { route: "/reviews/review-1" },
  );
}

describe("ReviewDetailPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getProjects.mockResolvedValue([]);
  });

  it("renders a requirement review as an inspection-only field and evidence record", async () => {
    api.getReview.mockResolvedValue({
      review_type: "REQUIREMENT_CHANGE",
      allowed_actions: [],
      review: {
        review_item_id: "review-1",
        correspondence_event_id: "correspondence-1",
        review_type: "REQUIREMENT_CHANGE",
        status: "PENDING",
        review_reason: "Requirement change requires review.",
        created_at: "2026-10-05T09:05:00Z",
        resolved_at: null,
        allowed_actions: [],
      },
      correspondence,
      handoff: {
        project_id: "project-1",
        state_transition_id: "transition-1",
        reconciliation: {
          existing_impacts: [{
            requirement_id: "requirement-1",
            disposition: "UPDATE_PROPOSED",
            proposed_state: "PARTIAL",
            proposed_expected_date: null,
            interpretation: "The evidence indicates partial completion.",
          }],
          new_requirements: [],
          concerns: [],
          conflicts: [],
        },
        m11_snapshot: { requirements: [{ requirement_id: "requirement-1", name: "Security review", description: null, current_state: "OPEN", expected_date: null }] },
        current_requirements: [{ requirement_id: "requirement-1", name: "Security review", description: null, state: "OPEN", expected_date: null }],
        transition_preview: {
          policy: { policy_version: "requirement-policy/1", decision: "REVIEW_REQUIRED", triggered_rule_ids: ["RID-401"], reasons: ["Human review is required."] },
          disposition: "REVIEW",
          requirement_effects: [],
        },
        evidence: [{ evidence_item_id: "evidence-1", requirement_id: "requirement-1", source_type: "BODY", page_number: null, section: null, excerpt: "partly complete", validity: "VALID", invalidation_reason: null }],
      },
    });
    const view = renderPage();

    const heading = await screen.findByRole("heading", { name: "Requirement review" });
    expect(heading.closest(".requirement-review-heading")).not.toBeNull();
    expect(heading.closest(".requirement-review-surface")).toBeNull();
    const source = view.container.querySelector(".requirement-correspondence-record dl");
    expect(source).toHaveTextContent("FromSenderSubjectRequirement updateReceived");
    expect(screen.getByRole("columnheader", { name: "Current" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Proposed" })).toBeInTheDocument();
    expect(screen.getByText("partly complete")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve|reject|assign/i })).not.toBeInTheDocument();
  });

  it("shows only the supported project-resolution decision actions", async () => {
    api.getReview.mockResolvedValue({
      review_type: "PROJECT_RESOLUTION",
      allowed_actions: ["APPROVE", "ASSIGN_OR_CORRECT", "REJECT"],
      detail: {
        review: { review_item_id: "review-1", correspondence_event_id: "correspondence-1", status: "PENDING", review_reason: "Identity requires review.", created_at: "2026-10-05T09:05:00Z", resolved_at: null },
        state_transition_id: "transition-1",
        proposal_id: "proposal-1",
        policy_evaluation_id: "policy-1",
        correspondence,
        preview: {
          resolver_status: "MATCHED",
          current_project_ids: [],
          proposed_project_ids: ["project-1"],
          alternative_project_ids: [],
          valid_evidence_ids: ["evidence-1"],
          invalidated_evidence_ids: [],
          policy: { policy_version: "project-identity/1", decision: "REVIEW_REQUIRED", triggered_rule_ids: ["PID-401"], reasons: ["Human review is required."] },
          disposition: "REVIEW",
          requires_manual_project_assignment: false,
        },
        candidate_set: { candidates: [{ project_id: "project-1", project_code: "TW-001", project_name: "Test Project", project_status: "ACTIVE", signals: [{ signal_type: "KNOWN_CONTACT", matched_value: "sender@example.test", source: "CORRESPONDENCE", identifier_type: null, evidence_item_id: "evidence-1", exact: true, verified: false, previously_approved: false }] }] },
        resolution: { status: "MATCHED", project_ids: ["project-1"], evidence: [{ project_id: "project-1", interpretation: "The sender matches the project." }], conflicts: [], concerns: [] },
        evidence: [{ evidence_item_id: "evidence-1", attachment_id: null, source_type: "BODY", page_number: null, section: null, excerpt: "The review is partly complete.", validity: "VALID", invalidation_reason: null }],
      },
    });
    const view = renderPage();

    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign / correct" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(view.container.querySelector(".project-source-record .evidence-key")).not.toBeNull();
    expect(screen.getAllByText("E1").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /regenerate|retry|comment/i })).not.toBeInTheDocument();
  });

  it("renders a document revision review without mutation controls", async () => {
    api.getReview.mockResolvedValue({
      review_type: "DOCUMENT_REVISION",
      allowed_actions: [],
      review: {
        review_item_id: "review-1",
        correspondence_event_id: "correspondence-1",
        review_type: "DOCUMENT_REVISION",
        status: "PENDING",
        review_reason: "The same revision label exists with different content.",
        created_at: "2026-10-05T09:05:00Z",
        resolved_at: null,
        allowed_actions: [],
      },
      correspondence,
      attachment: {
        attachment_id: "attachment-1",
        filename: "Structural Plan R4.pdf",
        mime_type: "application/pdf",
        content_hash: "b".repeat(64),
      },
      state_transition_id: "transition-1",
      transition_status: "PREVIEWED",
      disposition: "REVIEW",
      incoming_document: {
        document_id: "document-2",
        source_attachment_id: "attachment-1",
        filename: "Structural Plan R4.pdf",
        project_id: "project-1",
        project_code: "TW-001",
        project_name: "Test Project",
        category: "Documents",
        document_family_key: "structural plan",
        revision_label: "R4",
        revision_normalized: "REV-4",
        revision_order: 4,
        content_hash: "b".repeat(64),
      },
      current_document: {
        document_id: "document-1",
        revision_normalized: "REV-4",
        revision_order: 4,
        content_hash: "a".repeat(64),
      },
      outcome: "REVIEW_REQUIRED",
      reasons: ["The same revision label exists with different content."],
      policy_version: "document-revision/1",
      triggered_rule_ids: ["DREV-200-SAME-REVISION-DIFFERENT-CONTENT-REVIEW"],
    });
    renderPage();

    expect(await screen.findByRole("heading", { name: "Document revision review" })).toBeInTheDocument();
    expect(screen.getByText("REV-4 (order 4)")).toBeInTheDocument();
    expect(screen.getByText("The same revision label exists with different content.")).toBeInTheDocument();
    expect(screen.getByText("document-revision/1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve|reject|assign|correct/i })).not.toBeInTheDocument();
  });
});
