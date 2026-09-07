import {
  apiClient,
  parseResponse,
  writeHeaders,
  type WriteOptions,
} from "@/shared/api/client";
import {
  customerSchema,
  listSchema,
  providerSetSchema,
  historySchema,
  reviewsSchema,
  auditSchema,
  type CustomerFilters,
  type CreateCustomerInput,
  type UpdateCustomerInput,
  type CustomerAction,
  type ActionInput,
} from "../model/types";
const endpoint = (id: string) => `/customers/${encodeURIComponent(id)}`;
export const customersService = {
  async list(filters: CustomerFilters, signal?: AbortSignal) {
    return parseResponse(
      listSchema,
      (await apiClient.get("/customers", { params: filters, signal })).data,
    );
  },
  async detail(id: string, signal?: AbortSignal) {
    return parseResponse(
      customerSchema,
      (await apiClient.get(endpoint(id), { signal })).data,
    );
  },
  async providers(id: string, signal?: AbortSignal) {
    return parseResponse(
      providerSetSchema,
      (await apiClient.get(`${endpoint(id)}/cloud-providers`, { signal })).data,
    );
  },
  async create(body: CreateCustomerInput, options: WriteOptions) {
    return parseResponse(
      customerSchema,
      (
        await apiClient.post("/customers", body, {
          headers: writeHeaders(options),
        })
      ).data,
    );
  },
  async update(id: string, body: UpdateCustomerInput, options: WriteOptions) {
    return parseResponse(
      customerSchema,
      (
        await apiClient.put(endpoint(id), body, {
          headers: writeHeaders(options),
        })
      ).data,
    );
  },
  async replaceProviders(id: string, codes: string[], options: WriteOptions) {
    return parseResponse(
      customerSchema,
      (
        await apiClient.put(
          `${endpoint(id)}/cloud-providers`,
          { cloudProviders: codes },
          { headers: writeHeaders(options) },
        )
      ).data,
    );
  },
  async transition(
    id: string,
    action: CustomerAction,
    body: ActionInput,
    options: WriteOptions,
  ) {
    return parseResponse(
      customerSchema,
      (
        await apiClient.post(`${endpoint(id)}/${action}`, body, {
          headers: writeHeaders(options),
        })
      ).data,
    );
  },
  async history(id: string, page: number, signal?: AbortSignal) {
    return parseResponse(
      historySchema,
      (
        await apiClient.get(`${endpoint(id)}/status-history`, {
          params: { page, pageSize: 20 },
          signal,
        })
      ).data,
    );
  },
  async reviews(id: string, page: number, signal?: AbortSignal) {
    return parseResponse(
      reviewsSchema,
      (
        await apiClient.get(`${endpoint(id)}/reviews`, {
          params: { page, pageSize: 20 },
          signal,
        })
      ).data,
    );
  },
  async audit(id: string, page: number, signal?: AbortSignal) {
    return parseResponse(
      auditSchema,
      (
        await apiClient.get(`${endpoint(id)}/audit-log`, {
          params: { page, pageSize: 20 },
          signal,
        })
      ).data,
    );
  },
};
