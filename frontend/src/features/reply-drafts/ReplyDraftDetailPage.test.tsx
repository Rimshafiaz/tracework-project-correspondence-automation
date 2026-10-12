import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getReplyDraft: vi.fn(), editReplyDraft: vi.fn(), approveReplyDraft: vi.fn(),
  rejectReplyDraft: vi.fn(), sendReplyDraft: vi.fn(),
}));
vi.mock("../../api/replyDrafts", () => api);

import { renderWithProviders } from "../../test/render";
import { ReplyDraftDetailPage } from "./ReplyDraftDetailPage";

const draft = {
  id: "draft-1", follow_up_id: "follow-1", project_id: "project-1", requirement_id: "requirement-1",
  ai_proposal_id: "proposal-1", source_correspondence_event_id: "source-1", target_correspondence_event_id: "source-1", project_contact_id: "contact-1",
  reply_type: "OVERDUE_FOLLOW_UP", generated: { subject: "Generated", body: "Generated body" }, edited: null,
  effective: { subject: "Generated", body: "Generated body" }, status: "APPROVED", recipient_email: "client@example.test",
  gmail_thread_id: "thread", source_gmail_message_id: "message", approved_at: "2026-10-08T00:00:00Z", approved_by_subject: "operator",
  rejected_at: null, send_attempt_id: null, send_attempted_at: null, send_failure_code: null, sent_at: null, gmail_message_id: null, gmail_sent_thread_id: null,
  can_edit: true, can_approve: false, can_reject: true, can_send: true, can_retry_send: false, send_attention_required: false,
  generated_at: "2026-10-08T00:00:00Z", created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z",
} as const;

function renderPage() {
  return renderWithProviders(<Routes><Route path="/reply-drafts/:draftId" element={<ReplyDraftDetailPage />} /></Routes>, { route: "/reply-drafts/draft-1" });
}

describe("ReplyDraftDetailPage", () => {
  beforeEach(() => { Object.values(api).forEach((mock) => mock.mockReset()); api.getReplyDraft.mockResolvedValue(draft); });

  it("renders backend action availability and does not show retry merely from a failure state", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Reply draft" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry send" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Generated original" })).not.toBeInTheDocument();
  });

  it("shows retry only when the backend allows fresh send revalidation", async () => {
    api.getReplyDraft.mockResolvedValue({
      ...draft,
      status: "RETRYABLE_FAILURE",
      send_failure_code: "GMAIL_METADATA_INVALID",
      can_send: false,
      can_retry_send: true,
    });

    renderPage();

    expect(await screen.findByRole("button", { name: "Retry send" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  });

  it("edits through the API without changing the displayed generated original", async () => {
    const user = userEvent.setup();
    api.editReplyDraft.mockResolvedValue({ ...draft, effective: { subject: "Edited", body: "Edited body" }, edited: { subject: "Edited", body: "Edited body" } });
    renderPage();
    await screen.findByRole("button", { name: "Edit" });
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await user.clear(screen.getByLabelText("Subject"));
    await user.type(screen.getByLabelText("Subject"), "Edited");
    await user.click(screen.getByRole("button", { name: "Save edit" }));
    expect(api.editReplyDraft).toHaveBeenCalledWith("draft-1", { subject: "Edited", body: "Generated body" });
  });

  it("shows the generated original when an edit exists", async () => {
    api.getReplyDraft.mockResolvedValue({
      ...draft,
      edited: { subject: "Edited", body: "Edited body" },
      effective: { subject: "Edited", body: "Edited body" },
    });
    renderPage();
    expect(await screen.findByRole("heading", { name: "Generated original" })).toBeInTheDocument();
  });

  it("preserves email paragraphs and keeps generated-draft actions with the preview", async () => {
    const body = "Hi Marcus,\n\nCould you confirm the submission date?\n\nBest regards,\nRimsha";
    api.getReplyDraft.mockResolvedValue({ ...draft, status: "GENERATED", can_approve: true, can_send: false,
      effective: { subject: "Commissioning certificates", body }, generated: { subject: "Commissioning certificates", body } });
    renderPage();
    const preview = await screen.findByRole("region", { name: "Current reply" });
    expect(within(preview).getByRole("heading", { name: "Commissioning certificates" })).toBeInTheDocument();
    expect(preview.querySelector(".reply-draft-body")?.textContent).toBe(body);
    for (const name of ["Edit", "Approve", "Reject"]) expect(within(preview).getByRole("button", { name })).toBeInTheDocument();
    expect(screen.getByText("Generated")).toBeInTheDocument();
    for (const id of [draft.follow_up_id, draft.source_correspondence_event_id, draft.ai_proposal_id]) expect(screen.queryByText(id)).not.toBeInTheDocument();
  });
});
