import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { getProjects } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import { ApiError } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { TableLoading } from "../../components/LoadingState";
import { StatusBadge } from "../../components/StatusBadge";

export function ProjectsPage() {
  const projects = useQuery({
    queryKey: queryKeys.projects,
    queryFn: getProjects,
  });

  return (
    <section aria-labelledby="projects-title">
      <header className="page-header">
        <h1 id="projects-title">Projects</h1>
        <p>Project records available to Tracework</p>
      </header>

      {projects.isPending ? <TableLoading /> : null}
      {projects.isError ? (
        <ProjectsError error={projects.error} retry={() => void projects.refetch()} />
      ) : null}
      {projects.data?.length === 0 ? (
        <EmptyState message="No projects have been added yet." />
      ) : null}
      {projects.data && projects.data.length > 0 ? (
        <ProjectDirectory projects={projects.data} />
      ) : null}
    </section>
  );
}

export function ProjectDirectory({
  projects,
  basePath = "/projects",
}: {
  projects: import("../../api/types").ProjectSummary[];
  basePath?: string;
}) {
  return (
    <div className="record-table project-table">
      <div className="record-table-header" aria-hidden="true">
        <span>Code</span><span>Project</span><span>Status</span>
      </div>
      <ul className="record-table-body">
        {projects.map((project) => (
          <li key={project.id}>
            <Link className="project-row" to={`${basePath}/${project.id}`}>
              <span className="project-code">{project.project_code}</span>
              <span className="project-name">{project.name}</span>
              <StatusBadge status={project.status} />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ProjectsError({ error, retry }: { error: Error; retry: () => void }) {
  return (
    <ErrorState
      title="Projects could not be loaded"
      message={projectErrorMessage(error)}
      onRetry={retry}
    />
  );
}

function projectErrorMessage(error: Error): string {
  if (error instanceof ApiError && error.kind === "unavailable") {
    return "Tracework could not reach the API.";
  }
  return "The project list is not available.";
}
