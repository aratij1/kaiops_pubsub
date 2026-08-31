import { QueryClient } from "@tanstack/react-query";
import { ApiRequestError, ApiValidationError } from "../services/apiClient";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 45_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      retry: (failureCount, error) => {
        if (error instanceof ApiValidationError) return false;
        if (error instanceof ApiRequestError) return error.retryable && failureCount < 2;
        return failureCount < 1;
      },
      retryDelay: (attempt, error) => {
        if (error instanceof ApiRequestError && error.retryAfterMs) return error.retryAfterMs;
        const exponential = Math.min(750 * 2 ** attempt, 8_000);
        return exponential + Math.round(Math.random() * 250);
      },
    },
    mutations: {
      retry: false,
    },
  },
});
