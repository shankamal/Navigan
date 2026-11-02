import type { QueryClient } from "@tanstack/react-query";

const staleTime = 90_000;

/** Warm the first authenticated request for the workspace the user is approaching. */
export function prefetchWorkspaceData(queryClient: QueryClient, href: string) {
  const path = href.split("?", 1)[0];

  if (path === "/migrations") {
    return queryClient.prefetchQuery({
      queryKey: ["migrations"],
      queryFn: async ({ signal }) => {
        const { migrations } =
          await import("@/modules/migration-management/service");
        return migrations.list(signal);
      },
      staleTime,
    });
  }

  if (path === "/dashboard") {
    return Promise.all([
      queryClient.prefetchQuery({
        queryKey: ["customers", "summary"],
        queryFn: async ({ signal }) => {
          const { customersService } =
            await import("@/modules/customer-management/services/customers");
          return customersService.summary(signal);
        },
        staleTime,
      }),
      queryClient.prefetchQuery({
        queryKey: ["environment-count", "summary"],
        queryFn: async ({ signal }) => {
          const { environments } =
            await import("@/modules/environment-management/services/environments");
          return environments.summary(signal);
        },
        staleTime,
      }),
      queryClient.prefetchQuery({
        queryKey: ["cluster-count", "summary"],
        queryFn: async ({ signal }) => {
          const { clusters } =
            await import("@/modules/cluster-management/service");
          return clusters.summary(signal);
        },
        staleTime,
      }),
    ]);
  }

  if (path === "/customers") {
    const filters = { page: 0, pageSize: 5, sort: "createdAt,desc" } as const;
    return queryClient.prefetchQuery({
      queryKey: ["customers", "list", filters],
      queryFn: async ({ signal }) => {
        const { customersService } =
          await import("@/modules/customer-management/services/customers");
        return customersService.list(filters, signal);
      },
      staleTime,
    });
  }

  if (path === "/environments") {
    const filters = {
      page: 0,
      pageSize: 20,
      sort: "createdAt,desc",
      status: undefined,
    } as const;
    return queryClient.prefetchQuery({
      queryKey: ["environments", filters],
      queryFn: async ({ signal }) => {
        const { environments } =
          await import("@/modules/environment-management/services/environments");
        return environments.list(filters, signal);
      },
      staleTime,
    });
  }

  if (path === "/clusters") {
    const filters = { page: 0, pageSize: 20, status: undefined } as const;
    return queryClient.prefetchQuery({
      queryKey: ["clusters", filters],
      queryFn: async ({ signal }) => {
        const { clusters } =
          await import("@/modules/cluster-management/service");
        return clusters.list(filters, signal);
      },
      staleTime,
    });
  }

  return Promise.resolve();
}
