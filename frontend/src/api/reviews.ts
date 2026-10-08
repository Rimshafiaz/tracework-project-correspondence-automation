import { apiRequest } from "./client";
import type {
  ReviewDecisionResponse,
  RequirementReviewDecisionResponse,
  ReviewQueueSummary,
  ReviewReadDetail,
} from "./types";

export const getReviews = (): Promise<ReviewQueueSummary[]> =>
  apiRequest<ReviewQueueSummary[]>("/reviews");

export const getReview = (reviewId: string): Promise<ReviewReadDetail> =>
  apiRequest<ReviewReadDetail>(`/reviews/${encodeURIComponent(reviewId)}`);

export const approveProjectResolution = (reviewId: string) =>
  reviewAction(reviewId, "approve", {});

export const assignProjectResolution = (reviewId: string, projectIds: string[]) =>
  reviewAction(reviewId, "assign", { project_ids: projectIds });

export const rejectProjectResolution = (reviewId: string) =>
  reviewAction(reviewId, "reject", {});

export const approveRequirementReview = (reviewId: string) =>
  apiRequest<RequirementReviewDecisionResponse>(
    `/reviews/${encodeURIComponent(reviewId)}/approve`,
    { method: "POST" },
  );

export const rejectRequirementReview = (reviewId: string) =>
  apiRequest<RequirementReviewDecisionResponse>(
    `/reviews/${encodeURIComponent(reviewId)}/reject`,
    { method: "POST" },
  );

function reviewAction(
  reviewId: string,
  action: "approve" | "assign" | "reject",
  body: Record<string, unknown>,
): Promise<ReviewDecisionResponse> {
  return apiRequest<ReviewDecisionResponse>(
    `/reviews/project-resolution/${encodeURIComponent(reviewId)}/${action}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}
