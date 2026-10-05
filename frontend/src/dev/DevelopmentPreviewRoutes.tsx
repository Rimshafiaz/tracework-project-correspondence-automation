import { Route, Routes, Outlet } from "react-router";

import { AppShell } from "../components/AppShell";
import { DevelopmentPreviewDetail } from "./DevelopmentPreviewDetail";
import { DevelopmentPreviewProjects } from "./DevelopmentPreviewProjects";

export default function DevelopmentPreviewRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route element={<PreviewNotice />}>
          <Route index element={<DevelopmentPreviewProjects />} />
          <Route path=":projectId" element={<DevelopmentPreviewDetail />} />
        </Route>
      </Route>
    </Routes>
  );
}

export function PreviewNotice() {
  return (
    <>
      <p className="preview-notice">Development preview. Synthetic records only.</p>
      <Outlet />
    </>
  );
}
