"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  Cloud,
  FileSearch,
  Radar,
  Server,
  ShieldCheck,
} from "lucide-react";

import { useClusters } from "@/modules/cluster-management/hooks/queries";
import { useCustomers } from "@/modules/customer-management/hooks/queries";
import { useEnvironments } from "@/modules/environment-management/hooks/queries";
import { normalizeApiError } from "@/shared/api/client";
import { PageHeading } from "@/shared/components/ui";

import { useSourceCatalogue } from "./hooks";
import type { Migration } from "./model";
import { migrations } from "./service";
import styles from "./migration-management.module.css";

const steps = [
  { title: "Migration path", icon: Cloud },
  { title: "Source connection", icon: Server },
  { title: "Workload scope", icon: Radar },
  { title: "Target connection", icon: Cloud },
  { title: "Assessment checks", icon: ShieldCheck },
  { title: "Review", icon: ClipboardCheck },
];

export function AssessmentWizard() {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [customer, setCustomer] = useState("");
  const [targetEnvironment, setTargetEnvironment] = useState("");
  const [targetType, setTargetType] = useState("EXISTING_CLUSTER");
  const [targetConnection, setTargetConnection] = useState("");
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [migration, setMigration] = useState<Migration | null>(null);
  const [connectorToken, setConnectorToken] = useState("");
  const [sourceBusy, setSourceBusy] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [scopeSaved, setScopeSaved] = useState(false);

  const customersQuery = useCustomers({
    page: 0,
    pageSize: 100,
    status: "ACTIVE",
    sort: "name,asc",
  });
  const environmentsQuery = useEnvironments({
    page: 0,
    pageSize: 100,
    status: "ACTIVE",
    sort: "createdAt,desc",
  });
  const clustersQuery = useClusters({
    page: 0,
    pageSize: 100,
    status: "ACTIVE",
  });

  const customers = customersQuery.data?.items ?? [];
  const environments = (environmentsQuery.data?.items ?? []).filter(
    (environment) =>
      environment.customerId === customer &&
      environment.cloudProvider === "AWS" &&
      environment.kubernetesDistribution === "EKS" &&
      environment.status === "ACTIVE" &&
      Boolean(environment.approvedVersion),
  );
  const targetClusters = (clustersQuery.data?.items ?? []).filter(
    (cluster) =>
      cluster.customerId === customer &&
      cluster.environmentId === targetEnvironment &&
      cluster.platform === "EKS" &&
      cluster.status === "ACTIVE",
  );

  const selectedCustomer = customers.find(
    (item) => item.customerId === customer,
  );
  const selectedEnvironment = environments.find(
    (item) => item.environmentId === targetEnvironment,
  );
  const selectedTarget = targetClusters.find(
    (item) => item.clusterId === targetConnection,
  );

  const catalogueQuery = useSourceCatalogue(
    migration?.migrationId ?? "",
  );
  const sourceCatalogue = catalogueQuery.data?.catalogue ?? null;

  useEffect(() => {
    if (sourceCatalogue && namespaces.length === 0) {
      setNamespaces(
        sourceCatalogue.namespaces.map((item) => item.name),
      );
    }
  }, [sourceCatalogue, namespaces.length]);

  const canContinue = [
    name.trim().length >= 3 &&
      customer !== "" &&
      targetEnvironment !== "" &&
      targetType === "EXISTING_CLUSTER",
    Boolean(sourceCatalogue),
    namespaces.length > 0,
    targetConnection !== "",
    true,
    Boolean(
      migration &&
      sourceCatalogue &&
      selectedTarget &&
      namespaces.length > 0,
    ),
  ][step];

  function toggleNamespace(namespace: string) {
    setNamespaces((current) =>
      current.includes(namespace)
        ? current.filter((item) => item !== namespace)
        : [...current, namespace],
    );
  }

  async function prepareSourceConnector() {
    if (!selectedEnvironment || sourceBusy) return;

    setSourceBusy(true);
    setSourceError("");

    try {
      const created = await migrations.create({
        customerId: customer,
        name: name.trim(),
        source: {
          platform: "SELF_MANAGED_KUBERNETES",
          accessMode: "READ_ONLY_CONNECTOR",
        },
        target: {
          platform: "EKS",
          targetType: "EXISTING_CLUSTER",
          environmentId: selectedEnvironment.environmentId,
          environmentApprovedVersion: Number(
            selectedEnvironment.approvedVersion,
          ),
          endpointAccess: "PRIVATE",
        },
        scope: {
          namespaces: [],
          excludeNamespaces: [
            "kube-node-lease",
            "kube-public",
            "kube-system",
          ],
          includeClusterScopedResources: false,
          includePersistentData: false,
        },
      });

      const token = (
        crypto.randomUUID() + crypto.randomUUID()
      ).replaceAll("-", "");

      const enrolled = await migrations.discover(
        created.migrationId,
        created.version,
        token,
      );

      setConnectorToken(token);
      setMigration(enrolled);
    } catch (error) {
      setSourceError(normalizeApiError(error).message);
    } finally {
      setSourceBusy(false);
    }
  }

  async function saveAssessmentScope() {
    if (
      !migration ||
      !catalogueQuery.data ||
      !selectedEnvironment ||
      !selectedTarget ||
      namespaces.length === 0 ||
      sourceBusy
    ) {
      return;
    }

    setSourceBusy(true);
    setSourceError("");

    try {
      const updated = await migrations.update(
        migration.migrationId,
        {
          version: catalogueQuery.data.version,
          source: {
            platform: "SELF_MANAGED_KUBERNETES",
            accessMode: "READ_ONLY_CONNECTOR",
          },
          target: {
            platform: "EKS",
            targetType: "EXISTING_CLUSTER",
            environmentId: selectedEnvironment.environmentId,
            environmentApprovedVersion: Number(
              selectedEnvironment.approvedVersion,
            ),
            clusterId: selectedTarget.clusterId,
            clusterName: selectedTarget.clusterName,
            endpointAccess: "PRIVATE",
          },
          scope: {
            namespaces,
            excludeNamespaces: [
              "kube-node-lease",
              "kube-public",
              "kube-system",
            ],
            includeClusterScopedResources: false,
            includePersistentData: false,
          },
          changeReason:
            "Save discovered workload scope and target cluster",
        },
      );

      setMigration(updated);
      setScopeSaved(true);
    } catch (error) {
      setSourceError(normalizeApiError(error).message);
    } finally {
      setSourceBusy(false);
    }
  }

  return (
    <>
      <PageHeading
        eyebrow="MIGRATION"
        title="New migration assessment"
        description="Compare source workload requirements with target platform capabilities without modifying either environment."
        action={
          <Link href="/migrations" className="button button-secondary">
            <ArrowLeft size={17} />
            Back to assessments
          </Link>
        }
      />

      <div className={styles.securityNotice}>
        <ShieldCheck size={21} aria-hidden="true" />
        <div>
          <strong>Read-only assessment</strong>
          <p>
            Navigan will collect sanitized metadata only. Credentials,
            Secret values and application data are never included.
          </p>
        </div>
      </div>

      <section className={`panel ${styles.wizard}`}>
        <nav className={styles.steps} aria-label="Assessment steps">
          {steps.map((item, index) => {
            const Icon = item.icon;
            const complete = index < step;
            const active = index === step;

            return (
              <button
                key={item.title}
                type="button"
                className={`${styles.step} ${
                  active ? styles.activeStep : ""
                } ${complete ? styles.completeStep : ""}`}
                onClick={() => index <= step && setStep(index)}
                aria-current={active ? "step" : undefined}
              >
                <span className={styles.stepIcon}>
                  {complete ? <CheckCircle2 size={18} /> : <Icon size={18} />}
                </span>
                <span>
                  <small>Step {index + 1}</small>
                  <strong>{item.title}</strong>
                </span>
              </button>
            );
          })}
        </nav>

        <form
          className={styles.content}
          aria-label="New migration assessment"
          onSubmit={(event) => {
            event.preventDefault();
            void saveAssessmentScope();
          }}
        >
          {step === 0 && (
            <div className={styles.stepContent}>
              <header>
                <span className={styles.kicker}>Define the journey</span>
                <h2>What do you want to assess?</h2>
                <p>
                  Select the source and destination platforms. Only validated
                  migration paths can be selected.
                </p>
              </header>

              <label className="field">
                <span>Assessment name</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="RetailFlow migration feasibility"
                  maxLength={100}
                  autoComplete="off"
                />
                <small>
                  Use a name that identifies the application and destination.
                </small>
              </label>

              <div className={styles.contextGrid}>
                <label className="field">
                  <span>Active customer</span>
                  <select
                    value={customer}
                    onChange={(event) => {
                      setCustomer(event.target.value);
                      setTargetEnvironment("");
                      setTargetConnection("");
                    }}
                  >
                    <option value="">
                      {customersQuery.isPending
                        ? "Loading active customers…"
                        : "Select an active customer"}
                    </option>
                    {customers.map((item) => (
                      <option
                        key={item.customerId}
                        value={item.customerId}
                      >
                        {item.name} — {item.status}
                      </option>
                    ))}
                  </select>
                  <small>
                    Only customers available to your signed-in identity
                    will be shown.
                  </small>
                </label>

                <label className="field">
                  <span>Target environment</span>
                  <select
                    value={targetEnvironment}
                    disabled={!customer}
                    onChange={(event) => {
                      setTargetEnvironment(event.target.value);
                      setTargetConnection("");
                    }}
                  >
                    <option value="">
                      {!customer
                        ? "Select a customer first"
                        : environmentsQuery.isPending
                          ? "Loading approved environments…"
                          : "Select an approved EKS environment"}
                    </option>
                    {environments.map((environment) => (
                      <option
                        key={environment.environmentId}
                        value={environment.environmentId}
                      >
                        {environment.environmentName} — approved version{" "}
                        {environment.approvedVersion}
                      </option>
                    ))}
                  </select>
                  <small>
                    The environment supplies the approved target
                    configuration and governance baseline.
                  </small>
                </label>
              </div>

              <div className={styles.pathGrid}>
                <label className="field">
                  <span>Source platform</span>
                  <select defaultValue="SELF_MANAGED_KUBERNETES">
                    <option value="SELF_MANAGED_KUBERNETES">
                      Self-managed Kubernetes
                    </option>
                    <option disabled>Amazon EKS — planned</option>
                    <option disabled>Azure AKS — planned</option>
                    <option disabled>Google GKE — planned</option>
                  </select>
                </label>

                <div className={styles.pathArrow}>
                  <ArrowRight size={23} />
                </div>

                <label className="field">
                  <span>Target platform</span>
                  <select defaultValue="EKS">
                    <option value="EKS">Amazon EKS</option>
                    <option disabled>Amazon ECS — planned</option>
                    <option disabled>Azure AKS — planned</option>
                    <option disabled>Google GKE — planned</option>
                  </select>
                </label>
              </div>

              <fieldset className={styles.targetType}>
                <legend>Target type</legend>

                <label className={styles.optionCard}>
                  <input
                    type="radio"
                    name="targetType"
                    value="EXISTING_CLUSTER"
                    checked={targetType === "EXISTING_CLUSTER"}
                    onChange={(event) =>
                      setTargetType(event.target.value)
                    }
                  />
                  <span>
                    <strong>Existing EKS cluster</strong>
                    <small>
                      Assess against the actual capabilities of a
                      registered Amazon EKS cluster.
                    </small>
                  </span>
                </label>

                <label
                  className={`${styles.optionCard} ${styles.disabledOption}`}
                >
                  <input
                    type="radio"
                    name="targetType"
                    value="PLANNED_EKS"
                    disabled
                  />
                  <span>
                    <strong>Planned EKS platform</strong>
                    <small>
                      Assess against a proposed target design — future
                      capability.
                    </small>
                  </span>
                </label>
              </fieldset>

              <div className={styles.scopeCallout}>
                <strong>Supported assessment path</strong>
                <span>Self-managed Kubernetes → existing Amazon EKS</span>
              </div>
            </div>
          )}

          {step === 1 && (
            <div className={styles.stepContent}>
              <header>
                <span className={styles.kicker}>
                  Establish read-only access
                </span>
                <h2>Connect the source cluster</h2>
                <p>
                  Create a short-lived connector identity, install the
                  one-shot connector, and wait for its sanitized catalogue.
                </p>
              </header>

              {!migration && (
                <button
                  type="button"
                  className="button button-primary"
                  disabled={sourceBusy}
                  onClick={() => void prepareSourceConnector()}
                >
                  {sourceBusy
                    ? "Preparing connector…"
                    : "Prepare secure source connector"}
                </button>
              )}

              {migration?.discoveryConnector && (
                <div className={styles.connectionCard}>
                  <div>
                    <span className={styles.connectedDot} />
                    <strong>Connector identity prepared</strong>
                  </div>
                  <dl>
                    <div>
                      <dt>Migration</dt>
                      <dd>{migration.migrationId}</dd>
                    </div>
                    <div>
                      <dt>Connector</dt>
                      <dd>
                        {migration.discoveryConnector.connectorId}
                      </dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>
                        {sourceCatalogue
                          ? "Inventory ready"
                          : "Waiting for connector installation"}
                      </dd>
                    </div>
                  </dl>

                  {connectorToken && !sourceCatalogue && (
                    <div>
                      <strong>One-time connector token</strong>
                      <p>
                        Copy this token securely. It is kept only in this
                        browser page and is never stored by Navigan.
                      </p>
                      <code>{connectorToken}</code>
                    </div>
                  )}
                </div>
              )}

              {sourceCatalogue && (
                <div className={styles.connectionCard}>
                  <div>
                    <span className={styles.connectedDot} />
                    <strong>Source catalogue received</strong>
                  </div>
                  <dl>
                    <div>
                      <dt>Kubernetes</dt>
                      <dd>
                        {sourceCatalogue.sourceKubernetesVersion}
                      </dd>
                    </div>
                    <div>
                      <dt>Nodes</dt>
                      <dd>{sourceCatalogue.nodeCount}</dd>
                    </div>
                    <div>
                      <dt>Architectures</dt>
                      <dd>
                        {sourceCatalogue.architectures.join(", ") ||
                          "Not reported"}
                      </dd>
                    </div>
                    <div>
                      <dt>Namespaces</dt>
                      <dd>{sourceCatalogue.namespaces.length}</dd>
                    </div>
                  </dl>
                </div>
              )}

              {catalogueQuery.isError && (
                <p role="alert">
                  Unable to retrieve the source catalogue.
                </p>
              )}

              {sourceError && <p role="alert">{sourceError}</p>}

              <div className={styles.protectionList}>
                <span>✓ No Secret or ConfigMap access</span>
                <span>✓ No workload changes</span>
                <span>✓ No application data</span>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className={styles.stepContent}>
              <header>
                <span className={styles.kicker}>
                  Choose the discovered scope
                </span>
                <h2>Select workloads to assess</h2>
                <p>
                  These namespaces came from the sanitized source catalogue.
                  Select only the workloads intended for assessment.
                </p>
              </header>

              <fieldset className={styles.namespaceList}>
                <legend>Discovered namespaces</legend>
                {(sourceCatalogue?.namespaces ?? []).map((item) => {
                  const detail = Object.entries(item.resourceCounts)
                    .map(([kind, count]) => `${count} ${kind}`)
                    .join(" · ");

                  return (
                    <label key={item.name}>
                      <input
                        type="checkbox"
                        checked={namespaces.includes(item.name)}
                        onChange={() => toggleNamespace(item.name)}
                      />
                      <span>
                        <strong>{item.name}</strong>
                        <small>
                          {detail || "No supported resources reported"}
                        </small>
                      </span>
                    </label>
                  );
                })}
              </fieldset>

              <div className={styles.scopeSummary}>
                <FileSearch size={22} />
                <div>
                  <strong>
                    {namespaces.length} namespace selected
                  </strong>
                  <span>
                    Only sanitized metadata will be assessed.
                  </span>
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className={styles.stepContent}>
              <header>
                <span className={styles.kicker}>Inspect the destination</span>
                <h2>Select the target EKS cluster</h2>
                <p>
                  Eligible clusters are filtered by customer, approved
                  environment, platform status and connector health.
                </p>
              </header>

              <label className="field">
                <span>Eligible target EKS cluster</span>
                <select
                  value={targetConnection}
                  disabled={!targetEnvironment}
                  onChange={(event) =>
                    setTargetConnection(event.target.value)
                  }
                >
                  <option value="">
                    {!targetEnvironment
                      ? "Select the target environment first"
                      : clustersQuery.isPending
                        ? "Loading eligible EKS clusters…"
                        : "Select an eligible EKS cluster"}
                  </option>
                  {targetClusters.map((cluster) => (
                    <option
                      key={cluster.clusterId}
                      value={cluster.clusterId}
                    >
                      {cluster.clusterName} — {cluster.status}
                    </option>
                  ))}
                </select>
              </label>

              {selectedTarget && selectedEnvironment && (
                <div className={styles.connectionCard}>
                  <div>
                    <span className={styles.connectedDot} />
                    <strong>Eligible active EKS cluster</strong>
                  </div>
                  <dl>
                    <div>
                      <dt>Cluster</dt>
                      <dd>{selectedTarget.clusterName}</dd>
                    </div>
                    <div>
                      <dt>Platform</dt>
                      <dd>Amazon EKS</dd>
                    </div>
                    <div>
                      <dt>Environment</dt>
                      <dd>{selectedEnvironment.environmentName}</dd>
                    </div>
                    <div>
                      <dt>Approved version</dt>
                      <dd>{selectedEnvironment.approvedVersion}</dd>
                    </div>
                    <div>
                      <dt>Cluster status</dt>
                      <dd>{selectedTarget.status}</dd>
                    </div>
                    <div>
                      <dt>Capability data</dt>
                      <dd>Collected when assessment starts</dd>
                    </div>
                  </dl>
                  <span className={styles.previewBadge}>
                    Backend record
                  </span>
                </div>
              )}
            </div>
          )}

          {step === 4 && (
            <div className={styles.stepContent}>
              <header>
                <span className={styles.kicker}>Configure assessment</span>
                <h2>Select compatibility checks</h2>
                <p>
                  All recommended checks are enabled for the first assessment.
                </p>
              </header>

              <div className={styles.checkGrid}>
                {[
                  ["Workloads and Kubernetes APIs", "Versions, controllers and scheduling"],
                  ["Networking and ingress", "Services, DNS, ports and load balancers"],
                  ["Storage and data", "Claims, classes and persistence requirements"],
                  ["Identity and security", "RBAC, service accounts and policy requirements"],
                  ["Capacity and architecture", "CPU, memory, scaling and image architecture"],
                  ["Operations", "Health checks, monitoring and availability"],
                ].map(([title, detail]) => (
                  <label key={title} className={styles.checkCard}>
                    <input type="checkbox" defaultChecked />
                    <span>
                      <strong>{title}</strong>
                      <small>{detail}</small>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {step === 5 && (
            <div className={styles.stepContent}>
              <header>
                <span className={styles.kicker}>Confirm the assessment</span>
                <h2>Review before discovery starts</h2>
                <p>
                  Verify the assessment scope. No deployment or configuration
                  change will be performed.
                </p>
              </header>

              <div className={styles.reviewGrid}>
                <div><span>Assessment</span><strong>{name}</strong></div>
                <div>
                  <span>Customer</span>
                  <strong>{selectedCustomer?.name ?? "Not selected"}</strong>
                </div>
                <div>
                  <span>Target environment</span>
                  <strong>
                    {selectedEnvironment
                      ? `${selectedEnvironment.environmentName} — approved version ${selectedEnvironment.approvedVersion}`
                      : "Not selected"}
                  </strong>
                </div>
                <div>
                  <span>Migration path</span>
                  <strong>Self-managed Kubernetes → EKS</strong>
                </div>
                <div>
                  <span>Target type</span>
                  <strong>
                    {targetType === "EXISTING_CLUSTER"
                      ? "Existing EKS cluster"
                      : "Planned EKS platform"}
                  </strong>
                </div>
                <div>
                  <span>Source</span>
                  <strong>
                    {sourceCatalogue
                      ? `${sourceCatalogue.sourceKubernetesVersion} · ${sourceCatalogue.nodeCount} nodes`
                      : "Not connected"}
                  </strong>
                </div>
                <div>
                  <span>Target</span>
                  <strong>
                    {selectedTarget?.clusterName ?? "Not selected"}
                  </strong>
                </div>
                <div><span>Namespaces</span><strong>{namespaces.join(", ")}</strong></div>
                <div><span>Mode</span><strong>Read-only feasibility assessment</strong></div>
              </div>

              <div className={styles.finalNotice}>
                <ShieldCheck size={24} />
                <div>
                  <strong>Safe to assess</strong>
                  <p>
                    The source and target connectors receive read-only
                    assignments and submit sanitized, versioned snapshots.
                  </p>
                </div>
              </div>
            </div>
          )}

          <footer className={styles.actions}>
            <div>
              <span>Step {step + 1} of {steps.length}</span>
              <small>Assessment only · execution disabled</small>
            </div>

            <div>
              {step > 0 && (
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setStep((current) => current - 1)}
                >
                  Back
                </button>
              )}

              {step < steps.length - 1 ? (
                <button
                  type="button"
                  className="button button-primary"
                  disabled={!canContinue}
                  onClick={() => setStep((current) => current + 1)}
                >
                  Continue
                  <ArrowRight size={17} />
                </button>
              ) : (
                <button
                  type="submit"
                  className="button button-primary"
                  disabled={!canContinue || sourceBusy || scopeSaved}
                >
                  {scopeSaved
                    ? "Assessment scope saved"
                    : sourceBusy
                      ? "Saving assessment scope…"
                      : "Save assessment scope"}
                </button>
              )}
            </div>
          </footer>
        </form>
      </section>
    </>
  );
}
