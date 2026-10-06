import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

const useAuth = vi.hoisted(() => vi.fn());
vi.mock("./authContext", () => ({ useAuth }));

import { LoginPage } from "./LoginPage";

function renderLogin() {
  render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/projects" element={<p>Projects route</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  it("presents the real email and password sign-in form", () => {
    useAuth.mockReturnValue({ session: null, isLoading: false, signIn: vi.fn() });
    renderLogin();
    expect(screen.getByRole("heading", { name: "Sign in to Tracework" })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("placeholder", "operator@example.com");
    expect(screen.getByLabelText("Password")).toHaveAttribute("placeholder", "Enter password");
    expect(screen.getByText("Gmail and Drive authorization are configured separately from this sign-in.")).toBeInTheDocument();
  });

  it("submits credentials through the auth boundary", async () => {
    const signIn = vi.fn().mockResolvedValue(undefined);
    useAuth.mockReturnValue({ session: null, isLoading: false, signIn });
    renderLogin();
    await userEvent.type(screen.getByLabelText("Email"), "operator@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(signIn).toHaveBeenCalledWith("operator@example.test", "password");
    expect(await screen.findByText("Projects route")).toBeInTheDocument();
  });

  it("renders a safe credential error", async () => {
    const signIn = vi.fn().mockRejectedValue(new Error("Supabase internal detail"));
    useAuth.mockReturnValue({ session: null, isLoading: false, signIn });
    renderLogin();
    await userEvent.type(screen.getByLabelText("Email"), "operator@example.test");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Unable to sign in with those credentials.")).toBeInTheDocument();
    expect(screen.queryByText("Supabase internal detail")).not.toBeInTheDocument();
  });
});
