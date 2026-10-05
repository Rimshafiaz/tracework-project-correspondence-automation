import { useState } from "react";
import { useParams } from "react-router";

import { Link } from "react-router";
import { ProjectWorkspaceView } from "../features/projects/ProjectDetailPage";
import { previewActivity, previewLineage, previewWorkspaces } from "./previewData";

export function DevelopmentPreviewDetail() {
  const { projectId = "" } = useParams();
  const [transitionId, setTransitionId] = useState<string | null>(null);
  const workspace = previewWorkspaces[projectId];
  if (!workspace) {
    return (
      <section className="message-state" role="alert">
        <h2>Preview project not found</h2>
        <Link to="/__preview">Back to preview projects</Link>
      </section>
    );
  }
  return (
    <ProjectWorkspaceView
      workspace={workspace}
      activity={{ project_id: projectId, events: previewActivity[projectId] ?? [] }}
      onViewEvidence={setTransitionId}
      lineageTransitionId={transitionId}
      onCloseLineage={() => setTransitionId(null)}
      backHref="/__preview"
      developmentPreviewLineage={previewLineage}
    />
  );
}
