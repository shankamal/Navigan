import {
  apiClient,
  parseResponse,
  writeHeaders,
} from "@/shared/api/client";

import {
  assessmentResponseSchema,
  migrationSchema,
  sourceCatalogueResponseSchema,
  type CreateMigrationInput,
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

  assess: async (
    migrationId: string,
    version: number,
    connectorToken: string,
  ) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.post(
          `${base}/${migrationId}/assess`,
          {
            version,
            reason: "Collect detailed inventory and assess feasibility",
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

  assessment: async (migrationId: string) =>
    parseResponse(
      assessmentResponseSchema,
      (
        await apiClient.get(
          `${base}/${migrationId}/assessment`,
        )
      ).data,
    ),

  sourceCatalogue: async (migrationId: string) =>
    parseResponse(
      sourceCatalogueResponseSchema,
      (
        await apiClient.get(
          `${base}/${migrationId}/source-catalogue`,
        )
      ).data,
    ),

  update: async (
    migrationId: string,
    input: UpdateMigrationInput,
  ) =>
    parseResponse(
      migrationSchema,
      (
        await apiClient.put(
          `${base}/${migrationId}`,
          input,
          {
            headers: writeHeaders({
              key: crypto.randomUUID(),
              version: input.version,
            }),
          },
        )
      ).data,
    ),
};
