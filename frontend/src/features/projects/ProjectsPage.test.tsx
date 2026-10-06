import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getProjects = vi.hoisted(() => vi.fn());
vi.mock("../../api/projects", () => ({ getProjects }));

import { ProjectsError, ProjectsPage } from "./ProjectsPage";
import { project } from "../../test/fixtures";
import { renderWithProviders } from "../../test/render";

function renderPage() {
  return renderWithProviders(
    <Routes><Route path="/projects" element={<ProjectsPage />} /></Routes>,
    { route: "/projects" },
  );
}

describe("ProjectsPage", () => {
  beforeEach(() => getProjects.mockReset());

  it("shows compact table-shaped loading rows", async () => {
    let resolveProjects!: (value: []) => void;
    getProjects.mockReturnValue(new Promise<[]>(resolve => { resolveProjects = resolve; }));
    renderPage();
    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
    resolveProjects([]);
    await screen.findByText("No projects available.");
  });

  it("renders the real project fields returned by the API", async () => {
    getProjects.mockResolvedValue([project]);
    renderPage();
    expect(await screen.findByText("TW-101")).toBeInTheDocument();
    expect(screen.getByText("Release Controls")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Release Controls.*TW-101.*Active/i })).toHaveAttribute(
      "href",
      "/projects/project-1",
    );
  });

  it("renders first-run setup direction with the real creation route", async () => {
    getProjects.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText("No projects available.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New project" })).toHaveAttribute("href", "/projects/new");
  });

  it("renders a specific API failure with retry", () => {
    renderWithProviders(<ProjectsError error={new Error("backend detail")} retry={vi.fn()} />);
    expect(screen.getByText("Projects could not be loaded")).toBeInTheDocument();
    expect(screen.getByText("The project list is not available.")).toBeInTheDocument();
    expect(screen.queryByText("backend detail")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
