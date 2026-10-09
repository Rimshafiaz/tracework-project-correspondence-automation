import { environment } from "../lib/env";
import { queryClient } from "../lib/queryClient";
import { supabase } from "../lib/supabase";

export type ApiErrorKind =
  | "unauthorized"
  | "not_found"
  | "conflict"
  | "unavailable"
  | "unexpected";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly kind: ApiErrorKind,
    public readonly code?: string,
  ) {
    super(safeMessage(kind));
    this.name = "ApiError";
  }
}

function safeMessage(kind: ApiErrorKind): string {
  switch (kind) {
    case "unauthorized":
      return "Your session is no longer valid.";
    case "not_found":
      return "The requested record is not available.";
    case "conflict":
      return "Stored history could not be reconciled.";
    case "unavailable":
      return "Tracework could not reach the API.";
    default:
      return "The request could not be completed.";
  }
}

function errorKind(status: number): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 503) return "unavailable";
  return "unexpected";
}

async function invalidateSession(): Promise<void> {
  queryClient.clear();
  await supabase.auth.signOut({ scope: "local" });
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session?.access_token) {
    await invalidateSession();
    throw new ApiError(401, "unauthorized");
  }

  let response: Response;
  try {
    response = await fetch(`${environment.apiBaseUrl}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...init?.headers,
        Authorization: `Bearer ${data.session.access_token}`,
      },
    });
  } catch {
    throw new ApiError(0, "unavailable");
  }

  if (!response.ok) {
    const kind = errorKind(response.status);
    if (kind === "unauthorized") {
      await invalidateSession();
    }
    const body = await response.json().catch(() => null);
    const code = body?.detail?.code === "REMAINING_SUPPORTING_EVIDENCE"
      ? body.detail.code as string : undefined;
    throw new ApiError(response.status, kind, code);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(response.status, "unexpected");
  }
}
