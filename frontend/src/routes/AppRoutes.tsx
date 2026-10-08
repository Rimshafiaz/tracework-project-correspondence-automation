import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";

import { LoginPage } from "../auth/LoginPage";
import { ProtectedRoute } from "../auth/ProtectedRoute";
import { AppShell } from "../components/AppShell";
import { ProjectDetailPage } from "../features/projects/ProjectDetailPage";
import { ProjectsPage } from "../features/projects/ProjectsPage";
import { NewProjectPage } from "../features/projects/NewProjectPage";
import { ReviewDetailPage } from "../features/reviews/ReviewDetailPage";
import { ReviewsPage } from "../features/reviews/ReviewsPage";
import { ReplyDraftDetailPage } from "../features/reply-drafts/ReplyDraftDetailPage";

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
          <Route path="projects/new" element={<NewProjectPage />} />
          <Route path="projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="reviews" element={<ReviewsPage />} />
          <Route path="reviews/:reviewId" element={<ReviewDetailPage />} />
          <Route path="reply-drafts/:draftId" element={<ReplyDraftDetailPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  );
}
