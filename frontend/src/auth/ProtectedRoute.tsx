import { Navigate, Outlet, useLocation } from "react-router";

import { AppLoading } from "../components/LoadingState";
import { useAuth } from "./authContext";

export function ProtectedRoute() {
  const { session, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) return <AppLoading label="Restoring session" />;
  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}
