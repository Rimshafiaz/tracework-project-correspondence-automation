import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  getSession: vi.fn(),
  onAuthStateChange: vi.fn(),
  signInWithPassword: vi.fn(),
  signOut: vi.fn(),
  callback: null as null | ((event: string, session: unknown) => void),
  unsubscribe: vi.fn(),
}));

vi.mock("../lib/supabase", () => ({ supabase: { auth } }));

import { queryClient } from "../lib/queryClient";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./authContext";

function AuthProbe() {
  const { session, signIn, signOut } = useAuth();
  const [error, setError] = useState("");
  return (
    <div>
      <p>{session ? "Authenticated" : "Signed out"}</p>
      <button
        onClick={() => void signIn("operator@example.test", "password").catch(() => setError("failed"))}
      >
        Sign in test
      </button>
      <button onClick={() => void signOut()}>Sign out test</button>
      <p>{error}</p>
    </div>
  );
}

function renderProvider() {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider><AuthProbe /></AuthProvider>
    </QueryClientProvider>,
  );
}

describe("AuthProvider", () => {
  beforeEach(() => {
    auth.getSession.mockResolvedValue({ data: { session: null }, error: null });
    auth.onAuthStateChange.mockImplementation((callback) => {
      auth.callback = callback;
      return { data: { subscription: { unsubscribe: auth.unsubscribe } } };
    });
    auth.signOut.mockResolvedValue({ error: null });
  });

  it("restores an existing Supabase session", async () => {
    auth.getSession.mockResolvedValue({
      data: { session: { access_token: "restored-token" } },
      error: null,
    });
    renderProvider();
    expect(await screen.findByText("Authenticated")).toBeInTheDocument();
  });

  it("signs in through the Supabase auth abstraction", async () => {
    auth.signInWithPassword.mockResolvedValue({
      data: { session: { access_token: "new-token" } },
      error: null,
    });
    renderProvider();
    await screen.findByText("Signed out");
    await userEvent.click(screen.getByRole("button", { name: "Sign in test" }));
    expect(auth.signInWithPassword).toHaveBeenCalledWith({
      email: "operator@example.test",
      password: "password",
    });
    expect(await screen.findByText("Authenticated")).toBeInTheDocument();
  });

  it("clears product queries when the operator signs out", async () => {
    const clear = vi.spyOn(queryClient, "clear");
    renderProvider();
    await screen.findByText("Signed out");
    await userEvent.click(screen.getByRole("button", { name: "Sign out test" }));
    await waitFor(() => expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" }));
    expect(clear).toHaveBeenCalled();
  });

  it("responds to Supabase auth state changes", async () => {
    renderProvider();
    await screen.findByText("Signed out");
    act(() => auth.callback?.("SIGNED_IN", { access_token: "event-token" }));
    expect(screen.getByText("Authenticated")).toBeInTheDocument();
  });
});
