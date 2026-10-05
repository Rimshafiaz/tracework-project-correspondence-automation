import { NavLink, Outlet, useLocation } from "react-router";

import { useAuth } from "../auth/authContext";

export function AppShell() {
  const { signOut } = useAuth();
  const location = useLocation();
  const projectsHref = location.pathname.startsWith("/__preview")
    ? "/__preview"
    : "/projects";

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink className="wordmark wordmark-link" to={projectsHref}>
            Tracework
          </NavLink>
          <nav aria-label="Primary navigation">
            <NavLink
              className={({ isActive }) => isActive ? "nav-link nav-link-active" : "nav-link"}
              to={projectsHref}
            >
              Projects
            </NavLink>
          </nav>
          <button className="text-button" type="button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <main id="main-content" className="page-shell">
        <Outlet />
      </main>
    </div>
  );
}
