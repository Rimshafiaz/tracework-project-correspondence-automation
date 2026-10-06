export const queryKeys = {
  projects: ["projects"] as const,
  projectWorkspace: (projectId: string) =>
    ["projects", projectId, "workspace"] as const,
  projectActivity: (projectId: string) =>
    ["projects", projectId, "activity"] as const,
  transitionLineage: (transitionId: string) =>
    ["transitions", transitionId, "lineage"] as const,
  reviews: ["reviews"] as const,
  review: (reviewId: string) => ["reviews", reviewId] as const,
};
