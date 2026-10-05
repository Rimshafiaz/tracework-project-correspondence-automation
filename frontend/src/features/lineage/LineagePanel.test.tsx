import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getTransitionLineage = vi.hoisted(() => vi.fn());
vi.mock("../../api/projects", () => ({ getTransitionLineage }));

import { ApiError } from "../../api/client";
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
    ).toHaveLength(2);
    expect(screen.getByText("The review is partly complete.")).toBeInTheDocument();
    expect(screen.getByText(/review.pdf, page 2/)).toBeInTheDocument();
  });

  it("renders decision-time state separately from current state", async () => {
    getTransitionLineage.mockResolvedValue(lineage);
    renderWithProviders(<LineagePanel transitionId="transition-1" onClose={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "At decision time" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Current state" })).toBeInTheDocument();
    expect(screen.getByText(/"requirement_state": "OPEN"/)).toBeInTheDocument();
    expect(screen.getByText("SATISFIED")).toBeInTheDocument();
  });

  it("distinguishes historical evidence validity from current invalidation", async () => {
    getTransitionLineage.mockResolvedValue(lineage);
    renderWithProviders(<LineagePanel transitionId="transition-1" onClose={vi.fn()} />);
    await screen.findByText("At decision time");
    expect(screen.getByText("At proposal")).toBeInTheDocument();
    expect(screen.getByText("At policy")).toBeInTheDocument();
    expect(screen.getByText("At outcome")).toBeInTheDocument();
    expect(screen.getAllByText("VALID").length).toBeGreaterThan(0);
    expect(screen.getByText("INVALIDATED")).toBeInTheDocument();
    expect(screen.getByText(/Current invalidation:/)).toHaveTextContent(
      "The sender withdrew the attachment.",
    );
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
