import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 45_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      retry: (failureCount, error) => {
        if (error instanceof Error && error.name === "ApiValidationError") {
          return false;
        }
        return failureCount < 1;
      },
      retryDelay: 750,
    },
    mutations: {
      retry: false,
    },
  },
});
