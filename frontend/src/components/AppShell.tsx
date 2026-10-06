import { NavLink, Outlet } from "react-router";

import { useAuth } from "../auth/authContext";

export function AppShell() {
  const { signOut } = useAuth();

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink className="wordmark wordmark-link" to="/projects">
            Tracework
          </NavLink>
          <div className="topbar-actions">
            <nav aria-label="Primary navigation">
              <NavLink
                className={({ isActive }) => isActive ? "nav-link nav-link-active" : "nav-link"}
                to="/projects"
              >
                Projects
              </NavLink>
              <NavLink
                className={({ isActive }) => isActive ? "nav-link nav-link-active" : "nav-link"}
                to="/reviews"
              >
                Reviews
              </NavLink>
            </nav>
            <button className="text-button" type="button" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main id="main-content" className="page-shell">
        <Outlet />
      </main>
    </div>
  );
}
