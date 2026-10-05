import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { getProjectActivity, getProjectWorkspace } from "../../api/projects";
import { queryKeys } from "../../api/queryKeys";
import { ErrorState } from "../../components/ErrorState";
import { TableLoading } from "../../components/LoadingState";
import { StatusBadge } from "../../components/StatusBadge";
import type { EvidenceLineage, ProjectActivity, ProjectWorkspace } from "../../api/types";
import { ProjectActivityList } from "../activity/ProjectActivityList";
import { DevelopmentLineagePanel, LineagePanel } from "../lineage/LineagePanel";
import { RequirementsLedger } from "./RequirementsLedger";
import { humanizeIdentifierType } from "../../lib/format";

export function ProjectDetailPage() {
  const { projectId = "" } = useParams();
  const [transitionId, setTransitionId] = useState<string | null>(null);
  const workspace = useQuery({
    queryKey: queryKeys.projectWorkspace(projectId),
    queryFn: () => getProjectWorkspace(projectId),
    enabled: Boolean(projectId),
  });
  const activity = useQuery({
    queryKey: queryKeys.projectActivity(projectId),
    queryFn: () => getProjectActivity(projectId),
    enabled: Boolean(projectId),
  });

  if (workspace.isPending) {
    return (
      <div className="project-detail-loading">
        <span className="loading-line loading-line-short" />
        <TableLoading rows={3} />
      </div>
    );
  }

  if (workspace.isError) {
    if (workspace.error instanceof ApiError && workspace.error.kind === "not_found") {
      return (
        <ErrorState
          title="Project not found"
          message="This project is not available."
          backToProjects
        />
      );
    }
    return (
      <ErrorState
        title="Project could not be loaded"
        message="Tracework could not reach the API."
        onRetry={() => void workspace.refetch()}
        backToProjects
      />
    );
  }

  return (
    <ProjectWorkspaceView
      workspace={workspace.data}
      activity={activity.data ?? null}
      activityLoading={activity.isPending}
      activityError={activity.isError ? activity.error : null}
      onRetryActivity={() => void activity.refetch()}
      onViewEvidence={setTransitionId}
      lineageTransitionId={transitionId}
      onCloseLineage={() => setTransitionId(null)}
    />
  );
}

export function ProjectWorkspaceView({
  workspace,
  activity,
  activityLoading = false,
  activityError = null,
  onRetryActivity = () => undefined,
  onViewEvidence,
  lineageTransitionId = null,
  onCloseLineage = () => undefined,
  backHref = "/projects",
  developmentPreviewLineage,
}: {
  workspace: ProjectWorkspace;
  activity: ProjectActivity | null;
  activityLoading?: boolean;
  activityError?: Error | null;
  onRetryActivity?: () => void;
  onViewEvidence: (transitionId: string) => void;
  lineageTransitionId?: string | null;
  onCloseLineage?: () => void;
  backHref?: string;
  developmentPreviewLineage?: EvidenceLineage;
}) {
  const { project, identifiers, requirements } = workspace;
  const verifiedIdentifiers = identifiers.filter((item) => item.verified);
  return (
    <article>
      <Link className="back-link" to={backHref}>Projects</Link>
      <header className="project-header">
        <div>
          <p className="project-code project-code-heading">{project.project_code}</p>
          <h1>{project.name}</h1>
        </div>
        <StatusBadge status={project.status} />
      </header>

      {verifiedIdentifiers.length ? (
        <dl className="identifier-list">
          {verifiedIdentifiers.map((identifier) => (
            <div key={identifier.id}>
              <dt>{humanizeIdentifierType(identifier.identifier_type)}</dt>
              <dd>{identifier.display_value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <div className="workspace-columns">
        <RequirementsLedger requirements={requirements} />
        <section className="workspace-section activity-rail" aria-labelledby="activity-title">
          <div className="section-heading-row"><h2 id="activity-title">Project activity</h2></div>
          {activityLoading ? <TableLoading rows={3} /> : null}
          {activityError ? (
            <ErrorState
              title="Project history could not be loaded"
              message={activityError instanceof ApiError && activityError.kind === "conflict"
                ? "Stored history could not be reconciled."
                : "Tracework could not reach the API."}
              onRetry={onRetryActivity}
            />
          ) : null}
          {activity ? (
            <ProjectActivityList events={activity.events} onViewEvidence={onViewEvidence} />
          ) : null}
        </section>
      </div>

      {lineageTransitionId ? (
        developmentPreviewLineage ? (
          <DevelopmentLineagePanel
            lineage={developmentPreviewLineage}
            onClose={onCloseLineage}
          />
        ) : (
          <LineagePanel transitionId={lineageTransitionId} onClose={onCloseLineage} />
        )
      ) : null}
    </article>
  );
}
