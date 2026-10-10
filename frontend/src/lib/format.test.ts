import { describe, expect, it } from "vitest";

import { formatDateOnly, formatLabel, reviewReasonLabel } from "./format";

describe("formatDateOnly", () => {
  it("formats a date-only value without local timezone shifting", () => {
    const formatted = formatDateOnly("2026-10-05");
    expect(formatted).toContain("2026");
    expect(formatted).toContain("5");
  });

  it("labels a missing expected date", () => {
    expect(formatDateOnly(null)).toBe("Not set");
  });
});

describe("formatLabel", () => {
  it("formats API enum values for display", () => {
    expect(formatLabel("RETRYABLE_FAILURE")).toBe("Retryable failure");
  });
});

describe("reviewReasonLabel", () => {
  it("replaces the policy implementation wording used for expected-date reviews", () => {
    expect(reviewReasonLabel("Expected-date mutations require human review in this policy version."))
      .toBe("The proposed expected date needs approval.");
  });
});
