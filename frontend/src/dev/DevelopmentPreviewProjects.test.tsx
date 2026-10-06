import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../test/render";
import { DevelopmentPreviewProjects } from "./DevelopmentPreviewProjects";

describe("DevelopmentPreviewProjects", () => {
  it("uses the production Projects header structure", () => {
    renderWithProviders(<DevelopmentPreviewProjects />);

    expect(screen.getByRole("heading", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByText("Project records used to resolve incoming correspondence.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New project" })).toHaveAttribute("href", "/projects/new");
  });
});
