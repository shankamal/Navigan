"use client";
import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/shared/auth/auth-provider";
import { ApiError } from "@/shared/api/client";
import { RuntimeConfigGate } from "@/shared/config/runtime-config-gate";
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 90_000,
            refetchOnWindowFocus: false,
            retry: (count, error) =>
              count < 1 &&
              (!(error instanceof ApiError) ||
                error.status === 0 ||
                error.status >= 500),
          },
          mutations: { retry: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <RuntimeConfigGate>
        <AuthProvider>{children}</AuthProvider>
      </RuntimeConfigGate>
    </QueryClientProvider>
  );
}
