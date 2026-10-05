import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";

import { LoginPage } from "../auth/LoginPage";
import { ProtectedRoute } from "../auth/ProtectedRoute";
import { AppShell } from "../components/AppShell";
import { ProjectDetailPage } from "../features/projects/ProjectDetailPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";

const DevelopmentPreviewRoutes = import.meta.env.DEV
  ? lazy(() => import("../dev/DevelopmentPreviewRoutes"))
  : null;

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {DevelopmentPreviewRoutes ? (
        <Route
          path="/__preview/*"
          element={
            <Suspense fallback={null}>
              <DevelopmentPreviewRoutes />
            </Suspense>
          }
        />
      ) : null}
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/projects" replace />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="projects/:projectId" element={<ProjectDetailPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  );
}
