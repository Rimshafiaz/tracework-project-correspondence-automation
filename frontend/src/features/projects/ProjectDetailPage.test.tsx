import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getProjectWorkspace: vi.fn(),
  getProjectActivity: vi.fn(),
  getTransitionLineage: vi.fn(),
}));
vi.mock("../../api/projects", () => api);
vi.mock("../../api/replyDrafts", () => ({ getProjectReplyDrafts: vi.fn().mockResolvedValue([]) }));

import { ApiError } from "../../api/client";
import { activity, workspace } from "../../test/fixtures";
import { renderWithProviders } from "../../test/render";
import { ProjectDetailPage } from "./ProjectDetailPage";

function renderPage() {
  return renderWithProviders(
    <Routes><Route path="/projects/:projectId" element={<ProjectDetailPage />} /></Routes>,
    { route: "/projects/project-1" },
  );
}

describe("ProjectDetailPage", () => {
  beforeEach(() => {
    api.getProjectWorkspace.mockReset();
    api.getProjectActivity.mockReset();
    api.getProjectActivity.mockResolvedValue(activity);
  });

  it("renders authoritative project identity and only verified identifiers", async () => {
    api.getProjectWorkspace.mockResolvedValue(workspace);
    renderPage();
    expect(await screen.findByRole("heading", { name: "Release Controls" })).toBeInTheDocument();
    expect(screen.getByText("Repository URL")).toBeInTheDocument();
    expect(screen.getByText("https://example.test/release-controls")).toBeInTheDocument();
    expect(screen.queryByText("Unverified alias")).not.toBeInTheDocument();
  });

  it("renders authoritative requirement state, description, and expected date", async () => {
    api.getProjectWorkspace.mockResolvedValue(workspace);
    renderPage();
    expect(await screen.findByText("Security review")).toBeInTheDocument();
    expect(screen.getByText("Confirm the final review evidence.")).toBeInTheDocument();
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
    expect(screen.getByText(/Oct 5, 2026/)).toBeInTheDocument();
  });

  it("renders the requirement empty state without editing controls", async () => {
    api.getProjectWorkspace.mockResolvedValue({ ...workspace, requirements: [] });
    renderPage();
    expect(
      await screen.findByText("No requirements are currently recorded for this project."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /requirement/i })).not.toBeInTheDocument();
  });

  it("renders the approved project not-found state", async () => {
    api.getProjectWorkspace.mockRejectedValue(new ApiError(404, "not_found"));
    renderPage();
    expect(await screen.findByText("Project not found")).toBeInTheDocument();
    expect(screen.getByText("This project is not available.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to projects" })).toBeInTheDocument();
  });

  it("contains an activity failure without hiding the project workspace", async () => {
    api.getProjectWorkspace.mockResolvedValue(workspace);
    api.getProjectActivity.mockRejectedValue(new ApiError(409, "conflict"));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Release Controls" })).toBeInTheDocument();
    expect(await screen.findByText("Project history could not be loaded")).toBeInTheDocument();
    expect(screen.getByText("Stored history could not be reconciled.")).toBeInTheDocument();
  });
});
