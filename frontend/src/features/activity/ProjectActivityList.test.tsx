import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { linkedActivity, transitionActivity } from "../../test/fixtures";
import { ProjectActivityList } from "./ProjectActivityList";

describe("ProjectActivityList", () => {
  it("renders backend summaries in the supplied order", () => {
    render(
      <ProjectActivityList
        events={[transitionActivity, linkedActivity]}
        onViewEvidence={vi.fn()}
      />,
    );
    const summaries = screen.getAllByText(/Requirement|Correspondence/);
    expect(summaries[0]).toHaveTextContent(transitionActivity.summary);
    expect(summaries[1]).toHaveTextContent(linkedActivity.summary);
  });

  it("does not regenerate activity copy from the event type", () => {
    render(<ProjectActivityList events={[linkedActivity]} onViewEvidence={vi.fn()} />);
    expect(screen.getByText("Correspondence linked to this project")).toBeInTheDocument();
    expect(screen.queryByText("CORRESPONDENCE_LINKED")).not.toBeInTheDocument();
  });

  it("offers evidence only for a transition-backed event", async () => {
    const onViewEvidence = vi.fn();
    render(
      <ProjectActivityList
        events={[transitionActivity, linkedActivity]}
        onViewEvidence={onViewEvidence}
      />,
    );
    expect(screen.getAllByRole("button", { name: "View evidence" })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "View evidence" }));
    expect(onViewEvidence).toHaveBeenCalledWith("transition-1");
  });

  it("renders authenticated attribution without exposing the subject", () => {
    render(<ProjectActivityList events={[linkedActivity]} onViewEvidence={vi.fn()} />);
    expect(screen.getByText("Authenticated operator")).toBeInTheDocument();
    expect(screen.queryByText("operator-subject")).not.toBeInTheDocument();
  });

  it("renders the approved empty state", () => {
    render(<ProjectActivityList events={[]} onViewEvidence={vi.fn()} />);
    expect(screen.getByText("No project activity has been recorded yet.")).toBeInTheDocument();
  });
});
