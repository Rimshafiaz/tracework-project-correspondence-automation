import { apiRequest } from "./client";
import type { ReplyDraft, ReplyDraftContent, ReplyDraftSendResult } from "./types";

export const getReplyDraft = (draftId: string) => apiRequest<ReplyDraft>(`/reply-drafts/${encodeURIComponent(draftId)}`);
export const getProjectReplyDrafts = (projectId: string) => apiRequest<ReplyDraft[]>(`/projects/${encodeURIComponent(projectId)}/reply-drafts`);
export const editReplyDraft = (draftId: string, content: ReplyDraftContent) => apiRequest<ReplyDraft>(`/reply-drafts/${encodeURIComponent(draftId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(content) });
export const approveReplyDraft = (draftId: string) => apiRequest<ReplyDraft>(`/reply-drafts/${encodeURIComponent(draftId)}/approve`, { method: "POST" });
export const rejectReplyDraft = (draftId: string) => apiRequest<ReplyDraft>(`/reply-drafts/${encodeURIComponent(draftId)}/reject`, { method: "POST" });
export const sendReplyDraft = (draftId: string) => apiRequest<ReplyDraftSendResult>(`/reply-drafts/${encodeURIComponent(draftId)}/send`, { method: "POST" });
