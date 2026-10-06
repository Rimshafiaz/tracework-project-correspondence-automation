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
        <div><h1 id="projects-title">Projects</h1><p>Project records used to resolve incoming correspondence.</p></div>
        <Link className="primary-button button-link" to="/projects/new">New project</Link>
      </header>

      {projects.isPending ? <TableLoading /> : null}
      {projects.isError ? (
        <ProjectsError error={projects.error} retry={() => void projects.refetch()} />
      ) : null}
      {projects.data?.length === 0 ? (
        <div className="compact-empty"><EmptyState message="No projects available." /><p>Create a project to establish its identity and initial requirements.</p></div>
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
        <span>Project</span><span>Status</span>
      </div>
      <ul className="record-table-body">
        {projects.map((project) => (
          <li key={project.id}>
            <Link className="project-row" to={`${basePath}/${project.id}`}>
              <span className="project-record"><span className="project-name">{project.name}</span><span className="project-code">{project.project_code}</span></span>
              <StatusBadge status={project.status} />
            </Link>
          </li>
        ))}
      </ul>
      <footer className="register-footer"><span>{projects.length} {projects.length === 1 ? "project record" : "project records"}</span><span>Open a project to view requirements and correspondence history.</span></footer>
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
