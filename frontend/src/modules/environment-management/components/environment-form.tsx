"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CloudCog,
  Eye,
  GitBranch,
  Save,
  Send,
  ShieldCheck,
} from "lucide-react";
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
  type AwsDiscovery,
  type Environment,
  type EnvironmentInput,
  type Provider,
} from "../model/types";
import { cleanConfiguration } from "./configuration-fields";
import { AwsDiscoveryPanel } from "./aws-discovery-panel";

const containerPlatformCatalogue = [
  {
    group: "Amazon Web Services",
    options: [
      { value: "AWS/EKS", label: "AWS / Elastic Kubernetes Service (EKS)", supported: true },
      { value: "AWS/ECS", label: "AWS / Elastic Container Service (ECS)", supported: false },
    ],
  },
  {
    group: "Microsoft Azure",
    options: [
      { value: "AZURE/AKS", label: "Azure / Kubernetes Service (AKS)", supported: false },
      { value: "AZURE/CONTAINER_APPS", label: "Azure / Container Apps", supported: false },
    ],
  },
  {
    group: "Google Cloud",
    options: [
      { value: "GCP/GKE", label: "Google / Kubernetes Engine (GKE)", supported: false },
      { value: "GCP/CLOUD_RUN", label: "Google / Cloud Run", supported: false },
    ],
  },
  {
    group: "Red Hat",
    options: [
      { value: "REDHAT/OPENSHIFT", label: "Red Hat OpenShift Container Platform", supported: false },
      { value: "AWS/ROSA", label: "Red Hat OpenShift Service on AWS (ROSA)", supported: false },
      { value: "AZURE/ARO", label: "Azure Red Hat OpenShift (ARO)", supported: false },
      { value: "REDHAT/OSD", label: "OpenShift Dedicated", supported: false },
    ],
  },
  {
    group: "Enterprise and managed platforms",
    options: [
      { value: "OCI/OKE", label: "Oracle Kubernetes Engine (OKE)", supported: false },
      { value: "IBM/IKS", label: "IBM Cloud Kubernetes Service", supported: false },
      { value: "IBM/ROKS", label: "Red Hat OpenShift on IBM Cloud", supported: false },
      { value: "VMWARE/TANZU", label: "VMware Tanzu Kubernetes Grid", supported: false },
      { value: "SUSE/RANCHER", label: "SUSE Rancher", supported: false },
    ],
  },
  {
    group: "Open-source distributions",
    options: [
      { value: "CNCF/KUBERNETES", label: "CNCF Kubernetes / kubeadm", supported: false },
      { value: "CNCF/K3S", label: "K3s", supported: false },
      { value: "CNCF/RKE2", label: "RKE2", supported: false },
      { value: "CNCF/MICROK8S", label: "Canonical MicroK8s", supported: false },
    ],
  },
] as const;

function configurationCostCenter(
  configuration: EnvironmentInput["configuration"],
) {
  const tags = configuration.tags;
  if (!tags || typeof tags !== "object" || Array.isArray(tags)) return "";
  return typeof tags.CostCenter === "string" ? tags.CostCenter : "";
}

export function activeCustomerParams(search: string, page: number) {
  return {
    search,
    status: "ACTIVE" as const,
    page,
    pageSize: 50,
    sort: "name,asc" as const,
  };
}

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
  const [costCenter, setCostCenter] = useState(
    environment ? configurationCostCenter(environment.configuration) : "",
  );
  const [search, setSearch] = useState("");
  const [hasDiscovery, setHasDiscovery] = useState(
    Boolean(environment && Object.keys(environment.configuration).length),
  );
  const [discovery, setDiscovery] = useState<AwsDiscovery>();
  const [reviewing, setReviewing] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const [customerPage, setCustomerPage] = useState(0);
  const customers = useQuery({
    queryKey: ["environment-customers", search, customerPage],
    queryFn: async () =>
      parseResponse(
        customerListSchema,
        (
          await apiClient.get("/customers", {
            params: activeCustomerParams(search, customerPage),
          })
        ).data,
      ),
    enabled: !environment,
  });
  const [providers, setProviders] = useState<string[]>(
    environment ? [environment.cloudProvider] : [],
  );
  const isEks =
    input.cloudProvider === "AWS" && input.kubernetesDistribution === "EKS";
  const schema = useConfigurationSchema(
    input.kubernetesDistribution,
    input.configurationSchemaVersion,
    isEks,
  );
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const mutation = useMutation({
    mutationFn: async ({
      submitAfterSave = false,
    }: {
      submitAfterSave?: boolean;
    }) => {
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
      const saved = environment
        ? environments.update(environment.environmentId, clean, options)
        : environments.create(clean, options);
      const draft = await saved;
      if (!submitAfterSave) return draft;
      return environments.action(
        draft.environmentId,
        environment?.status === "REJECTED" ? "resubmit" : "submit",
        { version: draft.version, comments: "Submitted from environment review." },
        { key: crypto.randomUUID(), version: draft.version },
      );
    },
    onSuccess: async (value) => {
      await cache.invalidateQueries({ queryKey: ["environments"] });
      await cache.invalidateQueries({
        queryKey: ["environment", value.environmentId],
      });
      router.push(`/environments/${value.environmentId}`);
    },
  });
  const canEdit = identity?.roles.some((r) => r === "CLOUD_ENGINEER");
  if (!canEdit)
    return (
      <ErrorNotice
        error={
          new Error(
            "Only a Cloud Engineer can create or edit an environment. Platform Architects review and approve submitted requests.",
          )
        }
      />
    );
  if (environment && !["DRAFT", "REJECTED"].includes(environment.status))
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
  const changeCostCenter = (value: string) => {
    setCostCenter(value);
    setInput((current) => {
      const existingTags = current.configuration.tags;
      const tags =
        existingTags &&
        typeof existingTags === "object" &&
        !Array.isArray(existingTags)
          ? existingTags
          : {};
      return {
        ...current,
        configuration: {
          ...current.configuration,
          tags: { ...tags, CostCenter: value },
        },
      };
    });
  };
  return (
    <>
      <Link className="back-link" href="/environments">
        <ArrowLeft size={16} />
        Back to environments
      </Link>
      <PageHeading
        eyebrow="Environment Management"
        title={
          environment
            ? `Edit ${environment.environmentName} revision`
            : input.cloudProvider === "AWS"
              ? "Create AWS environment profile"
              : "Create environment profile"
        }
        description={
          environment
            ? "Update the reusable cloud infrastructure baseline. Cluster configuration is managed separately through Cluster Setup requests."
            : "Save an incomplete draft now. Fields marked * are required before submission."
        }
      />
      {environment && (
        <section className="revision-context-banner" aria-label="Revision context">
          <span className="revision-context-icon">
            <GitBranch size={20} aria-hidden="true" />
          </span>
          <div>
            <strong>Editing draft revision v{environment.version}</strong>
            <p>
              Approved baseline v{environment.approvedVersion} remains{" "}
              {environment.approvedStatus?.toLowerCase() || "unchanged"} until
              this revision is reviewed and activated.
            </p>
          </div>
          <span className="security-chip">
            <ShieldCheck size={15} aria-hidden="true" />
            Active baseline protected
          </span>
        </section>
      )}
      <ol
        className="environment-stepper"
        aria-label={
          environment
            ? "Environment revision progress"
            : "Environment profile creation progress"
        }
      >
        {["Connection", "Discovery", "Resource selection", "Review"].map(
          (label, index) => (
            <li
              key={label}
              className={index <= (hasDiscovery ? 2 : 0) ? "active" : ""}
              aria-current={
                index === (hasDiscovery ? 2 : 0) ? "step" : undefined
              }
            >
              <span>{index + 1}</span>
              <strong>{label}</strong>
            </li>
          ),
        )}
      </ol>
      <form
        ref={form}
        className="environment-form"
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate({ submitAfterSave: reviewing });
        }}
      >
        <fieldset
          disabled={mutation.isPending}
          className="panel panel-padding environment-fieldset"
        >
          <legend className="sr-only">Environment identity</legend>
          <div className="section-heading environment-form-heading">
            <span className="section-number">
              <CloudCog size={17} aria-hidden="true" />
            </span>
            <div>
              <h2>Environment identity</h2>
              <p className="muted">
                Choose the customer, platform, ownership and billing context
                before discovering cloud resources.
              </p>
            </div>
          </div>
          <div className="environment-identity-grid">
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
                  const provider = (
                    allowed.includes("AWS") ? "AWS" : allowed[0] || "AWS"
                  ) as Provider;
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
                  customers.data?.items.map((c) => (
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
              Container distribution *
              <select
                disabled={!!environment}
                value={`${input.cloudProvider}/${input.kubernetesDistribution}`}
                onChange={(e) => {
                  if (e.target.value !== "AWS/EKS") return;
                  setInput((v) => ({
                    ...v,
                    cloudProvider: "AWS",
                    kubernetesDistribution: "EKS",
                    configuration: {},
                  }));
                }}
              >
                {containerPlatformCatalogue.map((category) => (
                  <optgroup key={category.group} label={category.group}>
                    {category.options.map((option) => (
                      <option
                        key={option.value}
                        value={option.value}
                        disabled={
                          !option.supported ||
                          (option.value === "AWS/EKS" &&
                            providers.length > 0 &&
                            !providers.includes("AWS"))
                        }
                      >
                        {option.label}
                        {option.supported ? " · Available" : " · Coming soon"}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              <small>
                AWS EKS is currently available for discovery and provisioning.
                Other container platforms are shown as the product roadmap.
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
              Cost center *
              <input
                required
                maxLength={1024}
                value={costCenter}
                onChange={(e) => changeCostCenter(e.target.value)}
                placeholder="Enter approved billing or project code"
              />
              <small>Required governance tag for provisioning.</small>
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
        {isEks &&
          identity?.roles.includes("CLOUD_ENGINEER") && (
            <AwsDiscoveryPanel
              customerId={input.customerId}
              environmentType={input.environmentType}
              owner={identity.displayName}
              costCenter={costCenter}
              disabled={mutation.isPending}
              onApply={(configuration) => {
                setHasDiscovery(true);
                setInput((current) => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    ...configuration,
                  },
                }));
              }}
              onDiscovered={setDiscovery}
            />
          )}
        {isEks ? (
          <>
            <section className="panel panel-padding environment-config-summary">
              <h2>EKS environment profile baseline</h2>
              <p className="muted">
                {hasDiscovery
                  ? "The validated AWS baseline above is attached to this draft. Save the draft to continue its review and approval workflow."
                  : "Connect the AWS account, review eligible resources and apply the selected baseline. Raw schema fields are intentionally hidden from this guided flow."}
              </p>
              <span
                className={
                  hasDiscovery ? "security-chip" : "security-chip needs-review"
                }
              >
                {hasDiscovery ? "Baseline applied" : "Baseline not applied"}
              </span>
            </section>
          </>
        ) : (
          <section className="panel panel-padding environment-config">
            <h2>Container distribution not yet available</h2>
            <p className="muted">
              Navigan currently provisions AWS EKS environments. The selected
              container platform will receive its own discovery, bootstrap,
              environment configuration, and provisioning workflow in a future
              release.
            </p>
            <span className="security-chip needs-review">Coming soon</span>
          </section>
        )}
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
        {reviewing && (
          <section
            className="panel panel-padding environment-review-panel"
            aria-label="Review environment before submission"
          >
            <div className="section-heading">
              <span className="section-number">
                <Eye size={17} aria-hidden="true" />
              </span>
              <div>
                <span className="eyebrow">REVIEW AND SUBMIT</span>
                <h2>Confirm the environment baseline</h2>
                <p className="muted">
                  Review the ownership and approved AWS resource selections.
                  Submitting sends this revision to a Platform Architect.
                </p>
              </div>
            </div>
            <dl className="details-grid">
              <div>
                <dt>Environment</dt>
                <dd>{input.environmentName || "Not provided"}</dd>
              </div>
              <div>
                <dt>Environment type</dt>
                <dd>{input.environmentType || "Not provided"}</dd>
              </div>
              <div>
                <dt>Container distribution</dt>
                <dd>{input.cloudProvider} / {input.kubernetesDistribution}</dd>
              </div>
              <div>
                <dt>Cost center</dt>
                <dd>{costCenter || "Not provided"}</dd>
              </div>
              <div>
                <dt>AWS account</dt>
                <dd>
                  {String(
                    (
                      input.configuration.account as
                        | Record<string, unknown>
                        | undefined
                    )?.accountId || "Not selected",
                  )}
                </dd>
              </div>
              <div>
                <dt>Baseline</dt>
                <dd>{hasDiscovery ? "Verified and attached" : "Not applied"}</dd>
              </div>
            </dl>
          </section>
        )}
        <div className="environment-actions environment-save-bar">
          <div>
            <strong>
              {reviewing
                ? "Submit environment for review"
                : environment
                  ? "Save revision draft"
                  : "Save environment draft"}
            </strong>
            <p className="muted">
              {reviewing
                ? "A Platform Architect will review this immutable revision before approval and activation."
                : "Drafts can be completed later and are not available for cluster setup until reviewed, approved and activated."}
            </p>
          </div>
          <div className="environment-save-buttons">
            {reviewing && (
              <Button
                type="button"
                variant="secondary"
                disabled={mutation.isPending}
                onClick={() => setReviewing(false)}
              >
                <ArrowLeft size={17} aria-hidden="true" />
                Back to edit
              </Button>
            )}
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
            {!reviewing && (
              <>
                <Button
                  type="button"
                  disabled={
                    mutation.isPending ||
                    !schema.data ||
                    !metadata.data ||
                    !input.customerId ||
                    !input.environmentName ||
                    !input.environmentType ||
                    !providers.length ||
                    !isEks
                  }
                  onClick={() => mutation.mutate({ submitAfterSave: false })}
                >
                  <Save size={17} aria-hidden="true" />
                  {mutation.isPending
                    ? "Saving…"
                    : environment
                      ? "Save revision"
                      : "Save as Draft"}
                </Button>
                <Button
                  type="button"
                  disabled={
                    mutation.isPending ||
                    !schema.data ||
                    !metadata.data ||
                    !input.customerId ||
                    !input.environmentName ||
                    !input.environmentType ||
                    !costCenter.trim() ||
                    !hasDiscovery ||
                    !providers.length ||
                    !isEks
                  }
                  onClick={() => {
                    if (form.current?.reportValidity()) {
                      setReviewing(true);
                      requestAnimationFrame(() =>
                        document
                          .querySelector(".environment-review-panel")
                          ?.scrollIntoView({
                            behavior: "smooth",
                            block: "center",
                          }),
                      );
                    }
                  }}
                >
                  <Eye size={17} aria-hidden="true" />
                  Review and Submit
                </Button>
              </>
            )}
            {reviewing && (
              <Button type="submit" disabled={mutation.isPending}>
                <Send size={17} aria-hidden="true" />
                {mutation.isPending ? "Submitting…" : "Submit for Review"}
              </Button>
            )}
          </div>
        </div>
      </form>
    </>
  );
}
