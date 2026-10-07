import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getReviews = vi.hoisted(() => vi.fn());
vi.mock("../../api/reviews", () => ({ getReviews }));

import { renderWithProviders } from "../../test/render";
import { ReviewsPage } from "./ReviewsPage";

const base = {
  correspondence_event_id: "correspondence-1",
  status: "PENDING" as const,
  review_reason: "Identity requires operator review.",
  created_at: "2026-10-05T09:00:00Z",
  resolved_at: null,
};

describe("ReviewsPage", () => {
  beforeEach(() => getReviews.mockReset());

  it("splits actionable and inspection-only reviews using API capabilities", async () => {
    getReviews.mockResolvedValue([
      { ...base, review_item_id: "review-1", review_type: "PROJECT_RESOLUTION", allowed_actions: ["APPROVE", "ASSIGN_OR_CORRECT", "REJECT"] },
      { ...base, review_item_id: "review-2", review_type: "REQUIREMENT_CHANGE", allowed_actions: [] },
      { ...base, review_item_id: "review-3", review_type: "DOCUMENT_REVISION", allowed_actions: [] },
    ]);
    renderWithProviders(<Routes><Route path="/reviews" element={<ReviewsPage />} /></Routes>, { route: "/reviews" });

    expect(await screen.findByRole("heading", { name: "Needs a decision" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Inspection only" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Project resolution/ })).toHaveAttribute("href", "/reviews/review-1");
    expect(screen.getByRole("link", { name: /Requirement change/ })).toHaveAttribute("href", "/reviews/review-2");
    expect(screen.getByRole("link", { name: /Document revision/ })).toHaveAttribute("href", "/reviews/review-3");
  });
});
