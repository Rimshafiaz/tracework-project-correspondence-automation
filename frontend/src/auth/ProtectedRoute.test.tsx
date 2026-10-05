import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

const useAuth = vi.hoisted(() => vi.fn());
vi.mock("./authContext", () => ({ useAuth }));

import { ProtectedRoute } from "./ProtectedRoute";

function renderRoute() {
  return render(
    <MemoryRouter initialEntries={["/projects"]}>
      <Routes>
        <Route path="/login" element={<p>Login screen</p>} />
        <Route element={<ProtectedRoute />}>
          <Route path="/projects" element={<p>Project workspace</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  it("redirects an unauthenticated user to login", () => {
    useAuth.mockReturnValue({ session: null, isLoading: false });
    renderRoute();
    expect(screen.getByText("Login screen")).toBeInTheDocument();
  });

  it("shows a session restoration state before routing", () => {
    useAuth.mockReturnValue({ session: null, isLoading: true });
    renderRoute();
    expect(screen.getByLabelText("Restoring session")).toBeInTheDocument();
  });

  it("allows an authenticated session into the workspace", () => {
    useAuth.mockReturnValue({ session: { access_token: "token" }, isLoading: false });
    renderRoute();
    expect(screen.getByText("Project workspace")).toBeInTheDocument();
  });
});
