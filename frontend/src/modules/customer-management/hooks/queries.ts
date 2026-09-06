"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { customersService } from "../services/customers";
import type { Customer, CustomerFilters, CustomerStatus } from "../model/types";
import type { WriteOptions } from "@/shared/api/client";
export const customerKeys = {
  all: ["customers"] as const,
  detail: (id: string) => ["customers", "detail", id] as const,
};
export const useCustomers = (filters: CustomerFilters) =>
  useQuery({
    queryKey: ["customers", "list", filters],
    queryFn: ({ signal }) => customersService.list(filters, signal),
  });
export const useCustomer = (id: string) =>
  useQuery({
    queryKey: customerKeys.detail(id),
    queryFn: ({ signal }) => customersService.detail(id, signal),
    enabled: Boolean(id),
  });
export const useCustomerProviders = (id: string) =>
  useQuery({
    queryKey: ["customers", id, "providers"],
    queryFn: ({ signal }) => customersService.providers(id, signal),
  });
export const useCustomerCount = (status?: CustomerStatus) =>
  useQuery({
    queryKey: ["customers", "count", status],
    queryFn: async ({ signal }) =>
      (
        await customersService.list(
          { page: 0, pageSize: 1, sort: "createdAt,desc", status },
          signal,
        )
      ).pagination.totalElements,
  });
// A failed/ambiguous request keeps its key for an identical manual retry. A changed body/version gets a new key.
export function useCustomerWrite<T>(
  operation: string,
  execute: (input: T, options: WriteOptions) => Promise<Customer>,
  version?: number,
) {
  const cache = useQueryClient();
  const pending = useRef<{ fingerprint: string; key: string } | null>(null);
  return useMutation({
    retry: false,
    mutationFn: async (input: T) => {
      const fingerprint = JSON.stringify({ operation, input, version });
      if (pending.current?.fingerprint !== fingerprint)
        pending.current = { fingerprint, key: crypto.randomUUID() };
      return execute(input, { key: pending.current.key, version });
    },
    onSuccess: async (customer) => {
      pending.current = null;
      cache.setQueryData(customerKeys.detail(customer.customerId), customer);
      await cache.invalidateQueries({ queryKey: customerKeys.all });
    },
  });
}
