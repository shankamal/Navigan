import { apiClient, parseResponse, writeHeaders } from "@/shared/api/client";

import {
  assessmentResponseSchema,
  migrationListSchema,
  migrationSchema,
  sourceClusterListSchema,
  sourceClusterSchema,
  sourceCatalogueResponseSchema,
  sourceEnrollmentSchema,
  type CreateMigrationInput,
  type CreateSourceClusterInput,
  type UpdateMigrationInput,
  type UpdateSourceClusterDeliveryInput,
} from "./model";

const base = "/migrations";

export const migrations = {
  list: async () =>
    parseResponse(
      migrationListSchema,
      (
        await apiClient.get(base, {
          params: { page: 0, pageSize: 100 },
        })
      ).data,
    ),

  get: async (migrationId: string) =>
    parseResponse(
      migrationSchema,
      (await apiClient.get(`${base}/${migrationId}`)).data,
    ),

  create: async (input: CreateMigrationInput) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(base, input, {
          headers: writeHeaders({
            key: crypto.randomUUID(),
          }),
        })
      ).data,
    ),

  discover: async (
    migrationId: string,
    version: number,
    connectorToken: string,
  ) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(
          `${base}/${migrationId}/discover`,
          {
            version,
            reason: "Begin read-only source discovery",
            connectorToken,
          },
          {
            headers: writeHeaders({
              key: crypto.randomUUID(),
              version,
            }),
          },
        )
      ).data,
    ),

  assess: async (migrationId: string, version: number) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(
          `${base}/${migrationId}/assess`,
          {
            version,
            reason: "Collect detailed inventory and assess feasibility",
          },
          {
            headers: writeHeaders({
              key: crypto.randomUUID(),
              version,
            }),
          },
        )
      ).data,
    ),

  assessment: async (migrationId: string) =>
    parseResponse(
      assessmentResponseSchema,
      (await apiClient.get(`${base}/${migrationId}/assessment`)).data,
    ),

  sourceCatalogue: async (migrationId: string) =>
    parseResponse(
      sourceCatalogueResponseSchema,
      (await apiClient.get(`${base}/${migrationId}/source-catalogue`)).data,
    ),

  update: async (migrationId: string, input: UpdateMigrationInput) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.put(`${base}/${migrationId}`, input, {
          headers: writeHeaders({
            key: crypto.randomUUID(),
            version: input.version,
          }),
        })
      ).data,
    ),

  action: async (
    migrationId: string,
    action: "submit" | "review" | "approve" | "reject",
    version: number,
    reason: string,
  ) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(
          `${base}/${migrationId}/${action}`,
          { version, reason },
          {
            headers: writeHeaders({
              key: crypto.randomUUID(),
              version,
            }),
          },
        )
      ).data,
    ),
};

const sourceClustersBase = "/source-clusters";

export const sourceClusters = {
  list: async (customerId: string) =>
    parseResponse(
      sourceClusterListSchema,
      (
        await apiClient.get(sourceClustersBase, {
          params: { customerId },
        })
      ).data,
    ),

  create: async (input: CreateSourceClusterInput) =>
    parseResponse(
      sourceClusterSchema,
      (
        await apiClient.post(sourceClustersBase, input, {
          headers: writeHeaders({ key: crypto.randomUUID() }),
        })
      ).data,
    ),

  updateDelivery: async (
    sourceClusterId: string,
    input: UpdateSourceClusterDeliveryInput,
  ) =>
    parseResponse(
      sourceClusterSchema,
      (
        await apiClient.put(`${sourceClustersBase}/${sourceClusterId}`, input, {
          headers: writeHeaders({
            key: crypto.randomUUID(),
            version: input.version,
          }),
        })
      ).data,
    ),

  enroll: async (sourceClusterId: string, version: number) =>
    parseResponse(
      sourceEnrollmentSchema,
      (
        await apiClient.post(
          `${sourceClustersBase}/${sourceClusterId}/enrollments`,
          {
            version,
            reason: "Connect source cluster for read-only assessment",
          },
          {
            headers: {
              "If-Match": String(version),
            },
          },
        )
      ).data,
    ),
};
