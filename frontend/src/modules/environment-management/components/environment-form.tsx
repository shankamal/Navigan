"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiError, parseResponse } from "@/shared/api/client";
import { listSchema as customerListSchema } from "@/modules/customer-management/model/types";
import { useAuth } from "@/shared/auth/auth-provider";
import {
  Button,
  ErrorNotice,
  Loading,
  PageHeading,
} from "@/shared/components/ui";
import {
  useEnvironment,
  useMetadata,
  useConfigurationSchema,
} from "../hooks/queries";
import { environments } from "../services/environments";
import {
  distributions,
  type Environment,
  type EnvironmentInput,
  type Provider,
} from "../model/types";
import {
  ConfigurationFields,
  cleanConfiguration,
} from "./configuration-fields";
export function EnvironmentEditor({ id }: { id?: string }) {
  const query = useEnvironment(id || "");
  if (id && query.isPending) return <Loading label="Loading environment…" />;
  if (id && query.error) return <ErrorNotice error={query.error} />;
  return (
    <EnvironmentForm
      key={query.data?.environmentId || "new"}
      environment={query.data}
    />
  );
}
function EnvironmentForm({ environment }: { environment?: Environment }) {
  const { identity } = useAuth();
  const router = useRouter();
  const cache = useQueryClient();
  const metadata = useMetadata();
  const [input, setInput] = useState<EnvironmentInput>(
    environment
      ? {
          customerId: environment.customerId,
          cloudProvider: environment.cloudProvider,
          kubernetesDistribution: environment.kubernetesDistribution,
          environmentName: environment.environmentName,
          environmentType: environment.environmentType,
          description: environment.description,
          configurationSchemaVersion: environment.configurationSchemaVersion,
          configuration: environment.configuration,
        }
      : {
          customerId: "",
          cloudProvider: "AWS",
          kubernetesDistribution: "EKS",
          environmentName: "",
          environmentType: "",
          description: "",
          configurationSchemaVersion: "1.0",
          configuration: {},
        },
  );
  const [search, setSearch] = useState("");
  const [customerPage, setCustomerPage] = useState(0);
  const customers = useQuery({
    queryKey: ["environment-customers", search, customerPage],
    queryFn: async () =>
      parseResponse(
        customerListSchema,
        (
          await apiClient.get("/customers", {
            params: {
              search,
              page: customerPage,
              pageSize: 50,
              sort: "name,asc",
            },
          })
        ).data,
      ),
    enabled: !environment,
  });
  const [providers, setProviders] = useState<string[]>(
    environment ? [environment.cloudProvider] : [],
  );
  const schema = useConfigurationSchema(
    input.kubernetesDistribution,
    input.configurationSchemaVersion,
  );
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const mutation = useMutation({
    mutationFn: async () => {
      const clean = {
        ...input,
        configuration: cleanConfiguration(
          input.configuration,
        ) as EnvironmentInput["configuration"],
      };
      const body = JSON.stringify(clean);
      if (attempt.current?.body !== body)
        attempt.current = { body, key: crypto.randomUUID() };
      const options = {
        key: attempt.current!.key,
        version: environment?.version,
      };
      return environment
        ? environments.update(environment.environmentId, clean, options)
        : environments.create(clean, options);
    },
    onSuccess: async (value) => {
      await cache.invalidateQueries({ queryKey: ["environments"] });
      await cache.invalidateQueries({
        queryKey: ["environment", value.environmentId],
      });
      router.push(`/environments/${value.environmentId}`);
    },
  });
  const canEdit = identity?.roles.some(
    (r) =>
      r === "CLOUD_ENGINEER" || (environment && r === "PLATFORM_ARCHITECT"),
  );
  if (
    !canEdit ||
    (environment && !["DRAFT", "REJECTED"].includes(environment.status))
  )
    return (
      <ErrorNotice
        error={
          new Error("You cannot edit this environment in its current state.")
        }
      />
    );
  const change = <K extends keyof EnvironmentInput>(
    key: K,
    value: EnvironmentInput[K],
  ) => setInput((v) => ({ ...v, [key]: value }));
  return (
    <>
      <PageHeading
        eyebrow="Environment Management"
        title={environment ? "Edit environment" : "Create environment"}
        description="Save an incomplete draft now. Fields marked * are required before submission."
      />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <fieldset
          disabled={mutation.isPending}
          className="panel panel-padding environment-fieldset"
        >
          <legend>Environment identity</legend>
          <div className="form-grid">
            {!environment && (
              <label className="field">
                Find customer
                <input
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setCustomerPage(0);
                  }}
                  placeholder="Search customers by name"
                />
              </label>
            )}
            <label className="field">
              Customer *
              <select
                required
                disabled={!!environment}
                value={input.customerId}
                onChange={(e) => {
                  const customer = customers.data?.items.find(
                    (c) => c.customerId === e.target.value,
                  );
                  const allowed =
                    customer?.cloudProviders.filter(
                      (p) => p in distributions,
                    ) || [];
                  setProviders(allowed);
                  const provider = (allowed[0] || "AWS") as Provider;
                  setInput((v) => ({
                    ...v,
                    customerId: e.target.value,
                    cloudProvider: provider,
                    kubernetesDistribution: distributions[provider],
                    configuration: {},
                  }));
                }}
              >
                <option value="">Select customer</option>
                {environment ? (
                  <option value={environment.customerId}>
                    {environment.customerName}
                  </option>
                ) : (
                  customers.data?.items
                    .filter((c) => c.status !== "DEACTIVATED")
                    .map((c) => (
                      <option key={c.customerId} value={c.customerId}>
                        {c.name} · {c.status}
                      </option>
                    ))
                )}
              </select>
            </label>
            {!environment &&
              customers.data &&
              customers.data.pagination.totalPages > 1 && (
                <div>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={!customerPage}
                    onClick={() => setCustomerPage((p) => p - 1)}
                  >
                    Previous customers
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={
                      customerPage + 1 >= customers.data.pagination.totalPages
                    }
                    onClick={() => setCustomerPage((p) => p + 1)}
                  >
                    More customers
                  </Button>
                </div>
              )}
            <label className="field">
              Kubernetes distribution *
              <select
                disabled={!!environment}
                value={input.cloudProvider}
                onChange={(e) => {
                  const p = e.target.value as Provider;
                  setInput((v) => ({
                    ...v,
                    cloudProvider: p,
                    kubernetesDistribution: distributions[p],
                    configuration: {},
                  }));
                }}
              >
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {p} / {distributions[p as Provider]}
                  </option>
                ))}
              </select>
              <small>
                Changing customer or distribution resets configuration.
              </small>
            </label>
            <label className="field">
              Environment name *
              <input
                required
                maxLength={150}
                value={input.environmentName}
                onChange={(e) => change("environmentName", e.target.value)}
              />
            </label>
            <label className="field">
              Environment type *
              <select
                required
                value={input.environmentType}
                onChange={(e) => change("environmentType", e.target.value)}
              >
                <option value="">Select type</option>
                {metadata.data?.environmentTypes.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Description
              <textarea
                rows={3}
                maxLength={4000}
                value={input.description}
                onChange={(e) => change("description", e.target.value)}
              />
            </label>
          </div>
        </fieldset>
        {customers.error && <ErrorNotice error={customers.error} />}{" "}
        {metadata.error && (
          <ErrorNotice
            error={metadata.error}
            onRetry={() => metadata.refetch()}
          />
        )}
        <section
          className="panel panel-padding environment-config"
          key={`${input.customerId}-${input.kubernetesDistribution}`}
        >
          <h2>{input.kubernetesDistribution} infrastructure configuration</h2>
          <p className="muted">
            Approved infrastructure references only. Keep cluster versions, node
            sizing and credentials outside this baseline.
          </p>
          {schema.isPending ? (
            <Loading label="Loading configuration fields…" />
          ) : schema.error ? (
            <ErrorNotice
              error={schema.error}
              onRetry={() => schema.refetch()}
            />
          ) : (
            schema.data && (
              <fieldset
                disabled={mutation.isPending}
                className="environment-fieldset"
              >
                <ConfigurationFields
                  schema={schema.data}
                  value={input.configuration}
                  onChange={(value) =>
                    change(
                      "configuration",
                      value as EnvironmentInput["configuration"],
                    )
                  }
                />
              </fieldset>
            )
          )}
        </section>
        {mutation.error && <ErrorNotice error={mutation.error} />}{" "}
        {mutation.error instanceof ApiError &&
          Array.isArray(mutation.error.details?.fields) && (
            <ul className="notice notice-error">
              {(
                mutation.error.details.fields as {
                  field?: string;
                  message?: string;
                }[]
              ).map((v, i) => (
                <li key={i}>
                  {v.field}: {v.message}
                </li>
              ))}
            </ul>
          )}
        <div className="environment-actions">
          <Link
            className="button button-secondary"
            href={
              environment
                ? `/environments/${environment.environmentId}`
                : "/environments"
            }
          >
            Cancel
          </Link>
          <Button
            disabled={
              mutation.isPending ||
              !schema.data ||
              !metadata.data ||
              !input.customerId ||
              !providers.length
            }
          >
            {mutation.isPending ? "Saving…" : "Save draft"}
          </Button>
        </div>
      </form>
    </>
  );
}
