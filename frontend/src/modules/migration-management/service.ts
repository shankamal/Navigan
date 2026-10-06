import { apiClient, parseResponse, writeHeaders } from "@/shared/api/client";

import {
  assessmentResponseSchema,
  migrationSchema,
  sourceClusterListSchema,
  sourceClusterSchema,
  sourceCatalogueResponseSchema,
  sourceEnrollmentSchema,
  type CreateMigrationInput,
  type CreateSourceClusterInput,
  type UpdateMigrationInput,
} from "./model";

const base = "/migrations";

export const migrations = {
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
