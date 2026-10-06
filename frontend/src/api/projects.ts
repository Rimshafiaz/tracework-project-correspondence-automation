import { apiRequest } from "./client";
import type {
  EvidenceLineage,
  ProjectActivity,
  ProjectSetupRequest,
  ProjectSummary,
  ProjectWorkspace,
} from "./types";

export const getProjects = (): Promise<ProjectSummary[]> =>
  apiRequest<ProjectSummary[]>("/projects");

export const getProjectWorkspace = (projectId: string): Promise<ProjectWorkspace> =>
  apiRequest<ProjectWorkspace>(`/projects/${encodeURIComponent(projectId)}`);

export const getProjectActivity = (projectId: string): Promise<ProjectActivity> =>
  apiRequest<ProjectActivity>(
    `/projects/${encodeURIComponent(projectId)}/activity`,
  );

export const getTransitionLineage = (
  transitionId: string,
): Promise<EvidenceLineage> =>
  apiRequest<EvidenceLineage>(
    `/transitions/${encodeURIComponent(transitionId)}/lineage`,
  );

export const createProject = (request: ProjectSetupRequest): Promise<ProjectWorkspace> =>
  apiRequest<ProjectWorkspace>("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
