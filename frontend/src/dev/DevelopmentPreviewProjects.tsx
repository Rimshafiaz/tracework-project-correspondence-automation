import { ProjectDirectory } from "../features/projects/ProjectsPage";
import { previewProjects } from "./previewData";

export function DevelopmentPreviewProjects() {
  return (
    <section aria-labelledby="preview-projects-title">
      <header className="page-header">
        <h1 id="preview-projects-title">Projects</h1>
        <p>Project records available to Tracework</p>
      </header>
      <ProjectDirectory projects={previewProjects} basePath="/__preview" />
    </section>
  );
}
