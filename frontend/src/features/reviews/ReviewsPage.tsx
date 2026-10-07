import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { getReviews } from "../../api/reviews";
import { queryKeys } from "../../api/queryKeys";
import type { ReviewQueueSummary } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { TableLoading } from "../../components/LoadingState";
import { formatDateTime, reviewTypeLabel } from "../../lib/format";

export function ReviewsPage() {
  const reviews = useQuery({ queryKey: queryKeys.reviews, queryFn: getReviews });
  if (reviews.isPending) return <ReviewPageFrame><TableLoading rows={5} /></ReviewPageFrame>;
  if (reviews.isError) {
    return <ReviewPageFrame><ErrorState title="Reviews could not be loaded" message="Tracework could not reach the API." onRetry={() => void reviews.refetch()} /></ReviewPageFrame>;
  }

  const actionable = reviews.data.filter((review) => review.allowed_actions.length > 0);
  const inspection = reviews.data.filter((review) => review.allowed_actions.length === 0);
  return (
    <ReviewPageFrame pendingCount={reviews.data.length}>
      <ReviewRegister title="Needs a decision" description="Project-resolution reviews can be approved, corrected, or rejected." reviews={actionable} empty="No reviews currently need a decision." />
      <ReviewRegister title="Inspection only" description="Requirement and document revision reviews are readable here but have no mutation actions." reviews={inspection} empty="No inspection-only reviews are pending." />
    </ReviewPageFrame>
  );
}

function ReviewPageFrame({ children, pendingCount }: { children: React.ReactNode; pendingCount?: number }) {
  return (
    <section aria-labelledby="reviews-title">
      <header className="page-header"><div><h1 id="reviews-title">Review queue</h1><p>Cases Tracework held back from automatic mutation.</p></div>{pendingCount !== undefined ? <span className="page-header-count">{pendingCount} pending</span> : null}</header>
      {children}
    </section>
  );
}

function ReviewRegister({ title, description, reviews, empty }: { title: string; description: string; reviews: ReviewQueueSummary[]; empty: string }) {
  return (
    <section className="review-queue-section" aria-labelledby={`${title.replaceAll(" ", "-")}-title`}>
      <div className="review-register-heading"><h2 id={`${title.replaceAll(" ", "-")}-title`}>{title} <span aria-hidden="true">{reviews.length}</span></h2><p>{description}</p></div>
      {reviews.length === 0 ? <EmptyState message={empty} /> : (
        <div className="record-table review-table">
          <div className="record-table-header" aria-hidden="true"><span>Review</span><span>Reason</span><span>Source</span><span>Created</span><span></span></div>
          <ul className="record-table-body">
            {reviews.map((review) => (
              <li key={review.review_item_id}>
                <Link className="review-row" to={`/reviews/${review.review_item_id}`}>
                  <span className="review-type">{reviewTypeLabel(review.review_type)}</span>
                  <span>{review.review_reason}</span>
                  <span className="review-source">Correspondence {shortReference(review.correspondence_event_id)}</span>
                  <time dateTime={review.created_at}>{formatDateTime(review.created_at)}</time>
                  <span className="review-arrow" aria-hidden="true">›</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function shortReference(value: string): string {
  return `${value.slice(0, 4)}...`;
}
