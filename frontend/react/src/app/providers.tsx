import type { PropsWithChildren } from "react";
import { QueryClientProvider } from "@tanstack/react-query";

import { queryClient } from "./queryClient";
import { SessionProvider } from "./SessionContext";

/** Provider composition point for query, identity, and future telemetry providers. */
export function AppProviders({ children }: PropsWithChildren) {
  return <QueryClientProvider client={queryClient}><SessionProvider>{children}</SessionProvider></QueryClientProvider>;
}
