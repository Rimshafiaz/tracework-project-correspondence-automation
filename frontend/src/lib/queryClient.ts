import { QueryClient } from "@tanstack/react-query";

function shouldRetry(failureCount: number, error: Error): boolean {
  const status = (error as Error & { status?: number }).status;
  if (status !== undefined && [401, 404, 409].includes(status)) {
    return false;
  }
  return failureCount < 1;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export const queryClient = createQueryClient();
