import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createProject = vi.hoisted(() => vi.fn());
vi.mock("../../api/projects", () => ({ createProject }));

import { workspace } from "../../test/fixtures";
import { renderWithProviders } from "../../test/render";
import { NewProjectPage } from "./NewProjectPage";

function renderPage() {
  return renderWithProviders(
    <Routes>
      <Route path="/projects/new" element={<NewProjectPage />} />
      <Route path="/projects/:projectId" element={<p>Created workspace</p>} />
    </Routes>,
    { route: "/projects/new" },
  );
}

describe("NewProjectPage", () => {
  beforeEach(() => createProject.mockReset());

  it("creates a project without accepting or sending a project code", async () => {
    createProject.mockResolvedValue(workspace);
    renderPage();

    expect(screen.queryByLabelText(/project code/i)).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Project name"), "Release Controls");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(createProject.mock.calls[0]?.[0]).toEqual({
      name: "Release Controls",
      identifiers: [],
      contacts: [],
      requirements: [],
    });
    expect(await screen.findByText("Created workspace")).toBeInTheDocument();
  });

  it("adds only backend-supported optional setup fields", async () => {
    createProject.mockResolvedValue(workspace);
    renderPage();
    await userEvent.type(screen.getByLabelText("Project name"), "Release Controls");
    await userEvent.click(screen.getByRole("button", { name: "Add requirement" }));
    await userEvent.type(screen.getByLabelText("Requirement"), "Security review");
    expect(screen.queryByLabelText(/^state$/i)).not.toBeInTheDocument();
  });
});
