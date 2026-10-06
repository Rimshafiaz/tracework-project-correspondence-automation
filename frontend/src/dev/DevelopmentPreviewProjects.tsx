import { Link } from "react-router";

import { ProjectDirectory } from "../features/projects/ProjectsPage";
import { previewProjects } from "./previewData";

export function DevelopmentPreviewProjects() {
  return (
    <section aria-labelledby="preview-projects-title">
      <header className="page-header">
        <div><h1 id="preview-projects-title">Projects</h1><p>Project records used to resolve incoming correspondence.</p></div>
        <Link className="primary-button button-link" to="/projects/new">New project</Link>
      </header>
      <ProjectDirectory projects={previewProjects} basePath="/__preview" />
    </section>
  );
}
