import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  getSession: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock("../lib/supabase", () => ({ supabase: { auth } }));

import { apiRequest, ApiError } from "./client";
import { queryClient } from "../lib/queryClient";

describe("apiRequest", () => {
  beforeEach(() => {
    auth.getSession.mockResolvedValue({
      data: { session: { access_token: "supabase-token" } },
      error: null,
    });
    auth.signOut.mockResolvedValue({ error: null });
  });

  it("attaches the Supabase access token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest<{ ok: boolean }>("/projects")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/projects",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer supabase-token" }),
      }),
    );
  });

  it("clears the session and product cache after a 401", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    const clear = vi.spyOn(queryClient, "clear");

    await expect(apiRequest("/projects")).rejects.toMatchObject({
      status: 401,
      kind: "unauthorized",
    });
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" });
    expect(clear).toHaveBeenCalledOnce();
  });

  it("preserves the auth session after a 503", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));

    await expect(apiRequest("/projects")).rejects.toBeInstanceOf(ApiError);
    expect(auth.signOut).not.toHaveBeenCalled();
  });

  it("maps a network failure to a safe unavailable error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("secret network detail")));

    await expect(apiRequest("/projects")).rejects.toMatchObject({
      status: 0,
      kind: "unavailable",
      message: "Tracework could not reach the API.",
    });
  });

  it("supports empty successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(apiRequest("/empty")).resolves.toBeUndefined();
  });

  it("maps malformed successful JSON to a safe error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not-json", { status: 200 })));
    await expect(apiRequest("/invalid-json")).rejects.toMatchObject({
      kind: "unexpected",
      message: "The request could not be completed.",
    });
  });
});
