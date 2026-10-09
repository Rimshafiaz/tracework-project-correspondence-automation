import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getReview: vi.fn(),
  getProjects: vi.fn(),
  approveProjectResolution: vi.fn(),
  assignProjectResolution: vi.fn(),
  rejectProjectResolution: vi.fn(),
  approveRequirementReview: vi.fn(),
  rejectRequirementReview: vi.fn(),
}));

vi.mock("../../api/reviews", () => ({
  getReview: api.getReview,
  approveProjectResolution: api.approveProjectResolution,
  assignProjectResolution: api.assignProjectResolution,
  rejectProjectResolution: api.rejectProjectResolution,
  approveRequirementReview: api.approveRequirementReview,
  rejectRequirementReview: api.rejectRequirementReview,
}));
vi.mock("../../api/projects", () => ({ getProjects: api.getProjects }));

import { renderWithProviders } from "../../test/render";
import { ReviewDetailPage } from "./ReviewDetailPage";
import { ApiError } from "../../api/client";
import { queryClient } from "../../lib/queryClient";

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

function correctionDetail(kind: "CORRECTION" | "RETRACTION", resolved = false) {
  return {
    review_type: "RETRACTION_CORRECTION", allowed_actions: resolved ? [] : ["APPROVE", "REJECT"],
    review: { review_item_id: "review-1", status: resolved ? "APPROVED" : "PENDING", created_at: "2026-10-05T09:05:00Z" },
    correspondence,
    handoff: {
      project_id: "project-1", reconciliation: {
        existing_impacts: [], new_requirements: [], concerns: [], conflicts: [],
        corrections: [{ kind, requirement_id: "requirement-1", previous_state: "OPEN", previous_expected_date: "2026-10-10",
          proposed_state: null, proposed_expected_date: kind === "CORRECTION" ? "2026-10-20" : null,
          target_evidence_item_ids: ["old-evidence"], evidence: [{ excerpt: "Later explicit correction.", source_field: "BODY" }], interpretation: "Later correspondence corrects the obligation." }],
      },
      m11_snapshot: { requirements: [{ requirement_id: "requirement-1", name: "Security review" }] },
      current_requirements: [{ requirement_id: "requirement-1", name: "Security review", state: resolved && kind === "RETRACTION" ? "RETRACTED" : "OPEN", expected_date: "2026-10-10" }],
      transition_preview: { policy: { decision: "REVIEW_REQUIRED", reasons: ["Explicit human decision required."] } },
      evidence: [{ evidence_item_id: "old-evidence", source_type: "BODY", excerpt: "Original deadline was October 10.", validity: resolved ? "INVALIDATED" : "VALID" }],
    },
  };
}

describe("ReviewDetailPage", () => {
  beforeEach(() => {
    Object.values(api).forEach((mock) => mock.mockReset());
    api.getProjects.mockResolvedValue([]);
  });

  it("shows correction values and evidence using the existing review actions", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    api.getReview.mockResolvedValue(correctionDetail("CORRECTION"));
    renderPage();
    expect(await screen.findByText(/^Correction/)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Current value" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Proposed value" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Previous evidence" })).toBeInTheDocument();
    expect(screen.getByText("Original deadline was October 10.")).toBeInTheDocument();
    expect(screen.getByText("Later explicit correction.")).toBeInTheDocument();
    expect(screen.getByText("Oct 10, 2026")).toBeInTheDocument();
    expect(screen.getByText("Oct 20, 2026")).toBeInTheDocument();
    expect(screen.queryByText("REVIEW_REQUIRED")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve correction" }));
    expect(api.approveRequirementReview).toHaveBeenCalledWith("review-1");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["reviews", "review-1"] });
    invalidate.mockRestore();
  });

  it("explains remaining support without exposing internal errors", async () => {
    api.getReview.mockResolvedValue(correctionDetail("RETRACTION"));
    api.approveRequirementReview.mockRejectedValue(new ApiError(409, "conflict", "REMAINING_SUPPORTING_EVIDENCE"));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Approve retraction" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("other valid evidence still supports the requirement");
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("shows a resolved retraction as historical and removes decision controls", async () => {
    api.getReview.mockResolvedValue(correctionDetail("RETRACTION", true));
    renderPage();
    expect(await screen.findByText("This review has been approved.")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Previous value" })).toBeInTheDocument();
    expect(screen.getByText("Retracted — no longer applicable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("uses the existing reject action and displays its resolved outcome", async () => {
    const detail = correctionDetail("CORRECTION");
    api.getReview.mockResolvedValue(detail);
    const view = renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    expect(api.rejectRequirementReview).toHaveBeenCalledWith("review-1");
    view.unmount();
    api.getReview.mockResolvedValue({ ...detail, allowed_actions: [], review: { ...detail.review, status: "REJECTED" } });
    renderPage();
    expect(await screen.findByText("This review has been rejected.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
  });

  it("renders actionable requirement review controls and submits the human decision", async () => {
    api.getReview.mockResolvedValue({
      review_type: "REQUIREMENT_CHANGE",
      allowed_actions: ["APPROVE", "REJECT"],
      review: {
        review_item_id: "review-1",
        correspondence_event_id: "correspondence-1",
        review_type: "REQUIREMENT_CHANGE",
        status: "PENDING",
        review_reason: "Requirement change requires review.",
        created_at: "2026-10-05T09:05:00Z",
        resolved_at: null,
        allowed_actions: ["APPROVE", "REJECT"],
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
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(api.approveRequirementReview).toHaveBeenCalledWith("review-1");
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
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
