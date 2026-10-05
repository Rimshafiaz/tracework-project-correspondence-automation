import { describe, expect, it } from "vitest";

import { formatDateOnly } from "./format";

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
