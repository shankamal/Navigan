import {
  apiClient,
  parseResponse,
  writeHeaders,
  type WriteOptions,
} from "@/shared/api/client";
import {
  environmentSchema,
  listSchema,
  metadataSchema,
  recordsSchema,
  type EnvironmentInput,
  type Filters,
  type Action,
  type ActionInput,
  type HistoryKind,
  type ConfigurationSchema,
  type AwsDiscoveryInput,
  awsDiscoverySchema,
} from "../model/types";
const base = "/environments";
export const environments = {
  list: async (filters: Filters) =>
    parseResponse(
      listSchema,
      (await apiClient.get(base, { params: filters })).data,
    ),
  get: async (id: string) =>
    parseResponse(
      environmentSchema,
      (await apiClient.get(`${base}/${id}`)).data,
    ),
  metadata: async () =>
    parseResponse(
      metadataSchema,
      (await apiClient.get(`${base}/metadata`)).data,
    ),
  schema: async (
    distribution: string,
    version: string,
  ): Promise<ConfigurationSchema> =>
    (
      await apiClient.get<ConfigurationSchema>(
        `${base}/configuration-schemas/${distribution}/${version}`,
      )
    ).data,
  discoverAws: async (input: AwsDiscoveryInput) =>
    parseResponse(
      awsDiscoverySchema,
      (await apiClient.post(`${base}/discover/aws`, input)).data,
    ),
  create: async (input: EnvironmentInput, options: WriteOptions) =>
    parseResponse(
      environmentSchema,
      (await apiClient.post(base, input, { headers: writeHeaders(options) }))
        .data,
    ),
  update: async (
    id: string,
    input: EnvironmentInput,
    options: WriteOptions,
  ) => {
    const { customerId, cloudProvider, kubernetesDistribution, ...editable } =
      input;
    void customerId;
    void cloudProvider;
    void kubernetesDistribution;
    return parseResponse(
      environmentSchema,
      (
        await apiClient.put(
          `${base}/${id}`,
          { ...editable, version: options.version },
          { headers: writeHeaders(options) },
        )
      ).data,
    );
  },
  action: async (
    id: string,
    action: Action,
    input: ActionInput,
    options: WriteOptions,
  ) =>
    parseResponse(
      environmentSchema,
      (
        await apiClient.post(`${base}/${id}/${action}`, input, {
          headers: writeHeaders(options),
        })
      ).data,
    ),
  records: async (id: string, kind: HistoryKind, page: number) =>
    parseResponse(
      recordsSchema,
      (
        await apiClient.get(`${base}/${id}/${kind}`, {
          params: { page, pageSize: 10 },
        })
      ).data,
    ),
  version: async (id: string, version: number) =>
    parseResponse(
      environmentSchema,
      (await apiClient.get(`${base}/${id}/versions/${version}`)).data,
    ),
};
