import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { getProjectActivity, getProjectWorkspace } from "../../api/projects";
import { getProjectReplyDrafts } from "../../api/replyDrafts";
import { queryKeys } from "../../api/queryKeys";
import { ErrorState } from "../../components/ErrorState";
import { TableLoading } from "../../components/LoadingState";
import { StatusBadge } from "../../components/StatusBadge";
import type { EvidenceLineage, ProjectActivity, ProjectWorkspace } from "../../api/types";
import type { ReplyDraft } from "../../api/types";
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
  const replyDrafts = useQuery({
    queryKey: queryKeys.projectReplyDrafts(projectId),
    queryFn: () => getProjectReplyDrafts(projectId),
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
      replyDrafts={replyDrafts.data ?? []}
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
  replyDrafts = [],
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
  replyDrafts?: ReplyDraft[];
}) {
  const { project, identifiers, contacts, requirements } = workspace;
  const verifiedIdentifiers = identifiers.filter((item) => item.verified);
  return (
    <article>
      <Link className="back-link" to={backHref}>Projects</Link>
      <header className="project-header">
        <h1>{project.name}</h1>
        <span className="project-code project-code-heading">{project.project_code}</span>
        <StatusBadge status={project.status} />
      </header>

      <div className="project-context-register">
        <section aria-labelledby="identifiers-title"><h2 id="identifiers-title">Verified identifiers</h2>{verifiedIdentifiers.length ? <dl>{verifiedIdentifiers.map((identifier) => <div key={identifier.id}><dt>{humanizeIdentifierType(identifier.identifier_type)}</dt><dd>{identifier.display_value}</dd></div>)}</dl> : <p className="empty-state">No verified identifiers recorded.</p>}</section>
        <section aria-labelledby="contacts-title"><h2 id="contacts-title">Trusted contacts</h2>{contacts.filter((contact) => contact.is_active).length ? <dl>{contacts.filter((contact) => contact.is_active).map((contact) => <div className="contact-record" key={contact.id}><dt>{contact.display_name}</dt><dd>{contact.role ?? "Not specified"}</dd><dd>{contact.email}</dd></div>)}</dl> : <p className="empty-state">No trusted contacts recorded.</p>}</section>
      </div>

      <div className="workspace-registers">
        <RequirementsLedger requirements={requirements} />
        <section className="workspace-section" aria-labelledby="reply-drafts-title">
          <div className="section-heading-row"><h2 id="reply-drafts-title">Reply drafts</h2></div>
          {replyDrafts.length ? <ul>{replyDrafts.map((draft) => <li key={draft.id}><Link to={`/reply-drafts/${draft.id}`}>{draft.effective.subject}</Link> <StatusBadge status={draft.status} /></li>)}</ul> : <p className="empty-state">No reply drafts are available for this project.</p>}
        </section>
        <section className="workspace-section history-register" aria-labelledby="activity-title">
          <div className="section-heading-row"><h2 id="activity-title">Project history</h2></div>
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
