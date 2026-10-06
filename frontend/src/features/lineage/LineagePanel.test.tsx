import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getTransitionLineage = vi.hoisted(() => vi.fn());
vi.mock("../../api/projects", () => ({ getTransitionLineage }));

import { ApiError } from "../../api/client";
import { formatDateOnly } from "../../lib/format";
import { lineage } from "../../test/fixtures";
import { renderWithProviders } from "../../test/render";
import { LineageError, LineagePanel } from "./LineagePanel";

describe("LineagePanel", () => {
  beforeEach(() => getTransitionLineage.mockReset());

  it("loads source evidence and policy explanation", async () => {
    getTransitionLineage.mockResolvedValue(lineage);
    renderWithProviders(<LineagePanel transitionId="transition-1" onClose={vi.fn()} />);
    expect(await screen.findByText("Why this changed")).toBeInTheDocument();
    expect(
      screen.getAllByText("The proposed change has valid requirement-scoped evidence."),
    ).toHaveLength(1);
    expect(screen.getByText("The review is partly complete.")).toBeInTheDocument();
    expect(screen.getByText(/review.pdf, page 2/)).toBeInTheDocument();
  });

  it("renders decision-time state separately from current state", async () => {
    getTransitionLineage.mockResolvedValue(lineage);
    renderWithProviders(<LineagePanel transitionId="transition-1" onClose={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "At decision time" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Current state" })).toBeInTheDocument();
    expect(screen.getByText("Requirement change: OPEN to PARTIAL")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "OPEN" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "PARTIAL" })).toBeInTheDocument();
    expect(screen.getByText("SATISFIED")).toBeInTheDocument();
    expect(screen.queryByText(/"requirement_state"/)).not.toBeInTheDocument();
  });

  it("distinguishes historical evidence validity from current invalidation", async () => {
    getTransitionLineage.mockResolvedValue(lineage);
    renderWithProviders(<LineagePanel transitionId="transition-1" onClose={vi.fn()} />);
    await screen.findByText("At decision time");
    expect(screen.getByText("At proposal")).toBeInTheDocument();
    expect(screen.getByText("At policy")).toBeInTheDocument();
    expect(screen.getByText("At outcome")).toBeInTheDocument();
    expect(screen.getAllByText("Valid").length).toBeGreaterThan(0);
    expect(screen.getByText("Invalidated")).toBeInTheDocument();
    const decisionTime = screen.getByRole("heading", { name: "At decision time" }).closest("section");
    expect(decisionTime).not.toBeNull();
    expect(within(decisionTime as HTMLElement).getAllByText("Attachment text").length).toBeGreaterThan(0);
    expect(within(decisionTime as HTMLElement).queryByText("ATTACHMENT_TEXT")).not.toBeInTheDocument();
    expect(screen.getByText(/Current invalidation:/)).toHaveTextContent(
      "The sender withdrew the attachment.",
    );
  });

  it("formats primary policy and fallback transition values for readers", async () => {
    getTransitionLineage.mockResolvedValue({
      ...lineage,
      transition: {
        ...lineage.transition,
        requirement_effects: [],
        historical_current_state: { requirement_state: "OPEN", expected_date: "2026-10-12" },
        historical_proposed_state: { requirement_state: "PARTIAL", expected_date: "2026-10-12" },
      },
    });
    renderWithProviders(<LineagePanel transitionId="transition-1" onClose={vi.fn()} />);
    const why = (await screen.findByRole("heading", { name: "Why this changed" })).closest("section");
    expect(why).not.toBeNull();
    expect(within(why as HTMLElement).getByText("Allowed")).toBeInTheDocument();
    expect(screen.getByText("Requirement change: OPEN to PARTIAL")).toBeInTheDocument();
    expect(screen.getAllByText(formatDateOnly("2026-10-12")).length).toBeGreaterThan(0);
    expect(within(why as HTMLElement).queryByText("ALLOW_AUTO_ACTION")).not.toBeInTheDocument();
  });

  it("shows the backend completeness limitation for legacy history", async () => {
    getTransitionLineage.mockResolvedValue({
      ...lineage,
      completeness: "LEGACY_PARTIAL",
      completeness_notes: ["The original transition was not recorded."],
    });
    renderWithProviders(<LineagePanel transitionId="transition-1" onClose={vi.fn()} />);
    expect(await screen.findByText("Historical record is incomplete.")).toBeInTheDocument();
    expect(screen.getByText("The original transition was not recorded.")).toBeInTheDocument();
  });

  it("contains lineage integrity errors inside the panel", () => {
    renderWithProviders(
      <LineageError error={new ApiError(409, "conflict")} retry={vi.fn()} />,
    );
    expect(screen.getByText("History could not be loaded")).toBeInTheDocument();
    expect(screen.getByText("Stored history could not be reconciled.")).toBeInTheDocument();
  });

  it("calls the close boundary from the accessible close control", async () => {
    const onClose = vi.fn();
    getTransitionLineage.mockResolvedValue(lineage);
    renderWithProviders(<LineagePanel transitionId="transition-1" onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
