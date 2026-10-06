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

import {
  useMigrationAssessment,
  useSourceCatalogue,
  useSourceClusters,
} from "./hooks";
import { AssessmentReportCard } from "./assessment-report";
import type {
  Migration,
  SourceClusterRegistration,
  SourceEnrollment,
} from "./model";
import { migrations, sourceClusters } from "./service";
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
  const [sourceMode, setSourceMode] = useState<"EXISTING" | "REGISTER">(
    "REGISTER",
  );
  const [sourceClusterId, setSourceClusterId] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceDistribution, setSourceDistribution] = useState("");
  const [sourceLocationType, setSourceLocationType] = useState<
    "CLOUD" | "ON_PREMISES" | "OTHER"
  >("ON_PREMISES");
  const [sourceCloudProvider, setSourceCloudProvider] = useState<
    "AWS" | "AZURE" | "GCP" | "OCI" | "OTHER"
  >("AWS");
  const [sourceRegion, setSourceRegion] = useState("");
  const [registeredSource, setRegisteredSource] =
    useState<SourceClusterRegistration | null>(null);
  const [sourceEnrollment, setSourceEnrollment] =
    useState<SourceEnrollment | null>(null);
  const [sourceBusy, setSourceBusy] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [scopeSaved, setScopeSaved] = useState(false);
  const [assessmentBusy, setAssessmentBusy] = useState(false);
  const [assessmentError, setAssessmentError] = useState("");

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
  const sourceClustersQuery = useSourceClusters(customer);

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
  const availableSourceClusters = sourceClustersQuery.data?.items ?? [];
  const selectedSource =
    registeredSource ??
    availableSourceClusters.find(
      (item) => item.sourceClusterId === sourceClusterId,
    );

  const catalogueQuery = useSourceCatalogue(migration?.migrationId ?? "");
  const sourceCatalogue = catalogueQuery.data?.catalogue ?? null;
  const assessmentQuery = useMigrationAssessment(
    migration?.migrationId ?? "",
    Boolean(
      migration &&
      [
        "DISCOVERY_PENDING",
        "DISCOVERING",
        "ASSESSING",
        "ASSESSMENT_READY",
      ].includes(migration.status),
    ),
  );
  const assessment = assessmentQuery.data?.assessment ?? null;

  useEffect(() => {
    if (sourceCatalogue && namespaces.length === 0) {
      setNamespaces(sourceCatalogue.namespaces.map((item) => item.name));
    }
  }, [sourceCatalogue, namespaces.length]);

  const canContinue = [
    name.trim().length >= 8 &&
      name.trim().length <= 100 &&
      customer !== "" &&
      targetEnvironment !== "" &&
      targetType === "EXISTING_CLUSTER",
    Boolean(sourceCatalogue),
    namespaces.length > 0,
    targetConnection !== "",
    true,
    Boolean(
      migration && sourceCatalogue && selectedTarget && namespaces.length > 0,
    ),
  ][step];

  function toggleNamespace(namespace: string) {
    setNamespaces((current) =>
      current.includes(namespace)
        ? current.filter((item) => item !== namespace)
        : [...current, namespace],
    );
  }

  function downloadSourceBootstrap() {
    if (!sourceEnrollment || !selectedSource) return;

    const apiBaseUrl =
      process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_API_BASE_URL ?? "";
    const imageRepository =
      process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_IMAGE_REPOSITORY ?? "";
    const imageDigest =
      process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_IMAGE_DIGEST ?? "";
    if (!apiBaseUrl || !imageRepository || !imageDigest) {
      setSourceError(
        "The source connector image and API endpoint are not configured.",
      );
      return;
    }

    const bootstrap = JSON.stringify(
      {
        apiBaseUrl,
        sourceClusterId: selectedSource.sourceClusterId,
        enrollmentToken: sourceEnrollment.enrollmentToken,
        enrollmentExpiresAt: sourceEnrollment.expiresAt,
        imageRepository,
        imageDigest,
      },
      null,
      2,
    );
    const url = URL.createObjectURL(
      new Blob([bootstrap], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `navigan-source-${selectedSource.sourceClusterId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function createMigrationDraft(sourceId: string) {
    if (!selectedEnvironment) {
      throw new Error("Select the target environment first.");
    }

    return migrations.create({
      customerId: customer,
      name: name.trim(),
      source: {
        platform: "SELF_MANAGED_KUBERNETES",
        sourceClusterId: sourceId,
        accessMode: "READ_ONLY_CONNECTOR",
      },
      target: {
        platform: "EKS",
        targetType: "EXISTING_CLUSTER",
        environmentId: selectedEnvironment.environmentId,
        environmentApprovedVersion: Number(selectedEnvironment.approvedVersion),
        endpointAccess: "PRIVATE",
      },
      scope: {
        namespaces: [],
        excludeNamespaces: ["kube-node-lease", "kube-public", "kube-system"],
        includeClusterScopedResources: false,
        includePersistentData: false,
      },
    });
  }

  async function useExistingSourceCluster() {
    if (!sourceClusterId || sourceBusy) return;

    setSourceBusy(true);
    setSourceError("");

    try {
      setMigration(await createMigrationDraft(sourceClusterId));
    } catch (error) {
      setSourceError(normalizeApiError(error).message);
    } finally {
      setSourceBusy(false);
    }
  }

  async function registerSourceCluster() {
    if (!selectedEnvironment || sourceBusy) return;

    setSourceBusy(true);
    setSourceError("");

    try {
      const registered = await sourceClusters.create({
        customerId: customer,
        name: sourceName.trim(),
        distribution: sourceDistribution.trim() || undefined,
        registrationMethod: "LOCAL_KUBECONFIG",
        location: {
          type: sourceLocationType,
          cloudProvider:
            sourceLocationType === "CLOUD" ? sourceCloudProvider : undefined,
          region: sourceRegion.trim() || undefined,
        },
      });
      const enrollment = await sourceClusters.enroll(
        registered.sourceClusterId,
        registered.version,
      );
      const created = await createMigrationDraft(registered.sourceClusterId);

      setRegisteredSource(registered);
      setSourceClusterId(registered.sourceClusterId);
      setSourceEnrollment(enrollment);
      setMigration(created);
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
      const updated = await migrations.update(migration.migrationId, {
        version: catalogueQuery.data.version,
        source: {
          platform: "SELF_MANAGED_KUBERNETES",
          sourceClusterId,
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
          excludeNamespaces: ["kube-node-lease", "kube-public", "kube-system"],
          includeClusterScopedResources: false,
          includePersistentData: false,
        },
        changeReason: "Save discovered workload scope and target cluster",
      });

      setMigration(updated);
      setScopeSaved(true);
    } catch (error) {
      setSourceError(normalizeApiError(error).message);
    } finally {
      setSourceBusy(false);
    }
  }

  async function startDetailedAssessment() {
    if (
      !migration ||
      !scopeSaved ||
      assessmentBusy ||
      migration.status !== "INVENTORY_READY"
    ) {
      return;
    }

    setAssessmentBusy(true);
    setAssessmentError("");

    try {
      const started = await migrations.assess(
        migration.migrationId,
        migration.version,
      );

      setMigration(started);
    } catch (error) {
      setAssessmentError(normalizeApiError(error).message);
    } finally {
      setAssessmentBusy(false);
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
            Navigan will collect sanitized metadata only. Credentials, Secret
            values and application data are never included.
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
                  minLength={8}
                  maxLength={100}
                  required
                  aria-describedby="assessment-name-help"
                  aria-invalid={name.length > 0 && name.trim().length < 8}
                  autoComplete="off"
                />
                <small id="assessment-name-help">
                  {name.length > 0 && name.trim().length < 8
                    ? `Enter at least 8 characters (${name.trim().length}/8).`
                    : `${name.length}/100 characters. Use a name that identifies the application and destination.`}
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
                      <option key={item.customerId} value={item.customerId}>
                        {item.name} — {item.status}
                      </option>
                    ))}
                  </select>
                  <small>
                    Only customers available to your signed-in identity will be
                    shown.
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
                    The environment supplies the approved target configuration
                    and governance baseline.
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
                    onChange={(event) => setTargetType(event.target.value)}
                  />
                  <span>
                    <strong>Existing EKS cluster</strong>
                    <small>
                      Assess against the actual capabilities of a registered
                      Amazon EKS cluster.
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
                  Select a previously connected source or register any
                  Kubernetes cluster in AWS, Azure, GCP, OCI, on-premises, or
                  another location.
                </p>
              </header>

              {!migration && (
                <>
                  <fieldset className={styles.targetType}>
                    <legend>Source cluster</legend>
                    <label className={styles.optionCard}>
                      <input
                        type="radio"
                        name="sourceMode"
                        value="REGISTER"
                        checked={sourceMode === "REGISTER"}
                        onChange={() => setSourceMode("REGISTER")}
                      />
                      <span>
                        <strong>Register a new source cluster</strong>
                        <small>
                          Recommended when the cluster is not yet connected to
                          Navigan.
                        </small>
                      </span>
                    </label>
                    <label className={styles.optionCard}>
                      <input
                        type="radio"
                        name="sourceMode"
                        value="EXISTING"
                        checked={sourceMode === "EXISTING"}
                        onChange={() => setSourceMode("EXISTING")}
                      />
                      <span>
                        <strong>Use a connected source cluster</strong>
                        <small>
                          Reuse a read-only connector that was registered
                          earlier.
                        </small>
                      </span>
                    </label>
                  </fieldset>

                  {sourceMode === "EXISTING" && (
                    <div className={styles.sourceRegistration}>
                      <label className="field">
                        <span>Connected source cluster</span>
                        <select
                          value={sourceClusterId}
                          onChange={(event) =>
                            setSourceClusterId(event.target.value)
                          }
                        >
                          <option value="">
                            {sourceClustersQuery.isPending
                              ? "Loading source clusters…"
                              : "Select a source cluster"}
                          </option>
                          {availableSourceClusters.map((source) => (
                            <option
                              key={source.sourceClusterId}
                              value={source.sourceClusterId}
                              disabled={source.status === "REVOKED"}
                            >
                              {source.name} —{" "}
                              {source.status.replaceAll("_", " ")}
                            </option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        className="button button-primary"
                        disabled={!sourceClusterId || sourceBusy}
                        onClick={() => void useExistingSourceCluster()}
                      >
                        {sourceBusy
                          ? "Preparing assessment…"
                          : "Use selected source cluster"}
                      </button>
                    </div>
                  )}

                  {sourceMode === "REGISTER" && (
                    <div className={styles.sourceRegistration}>
                      <div className={styles.contextGrid}>
                        <label className="field">
                          <span>Source cluster name</span>
                          <input
                            value={sourceName}
                            minLength={3}
                            maxLength={100}
                            required
                            onChange={(event) =>
                              setSourceName(event.target.value)
                            }
                            placeholder="retailflow-source"
                            autoComplete="off"
                          />
                        </label>
                        <label className="field">
                          <span>Kubernetes distribution</span>
                          <input
                            value={sourceDistribution}
                            maxLength={100}
                            onChange={(event) =>
                              setSourceDistribution(event.target.value)
                            }
                            placeholder="kubeadm, OpenShift, Rancher…"
                            autoComplete="off"
                          />
                        </label>
                        <label className="field">
                          <span>Cluster location</span>
                          <select
                            value={sourceLocationType}
                            onChange={(event) =>
                              setSourceLocationType(
                                event.target.value as
                                  "CLOUD" | "ON_PREMISES" | "OTHER",
                              )
                            }
                          >
                            <option value="ON_PREMISES">On-premises</option>
                            <option value="CLOUD">Cloud account</option>
                            <option value="OTHER">Other location</option>
                          </select>
                        </label>
                        {sourceLocationType === "CLOUD" && (
                          <label className="field">
                            <span>Cloud provider</span>
                            <select
                              value={sourceCloudProvider}
                              onChange={(event) =>
                                setSourceCloudProvider(
                                  event.target.value as
                                    "AWS" | "AZURE" | "GCP" | "OCI" | "OTHER",
                                )
                              }
                            >
                              <option value="AWS">AWS</option>
                              <option value="AZURE">Microsoft Azure</option>
                              <option value="GCP">Google Cloud</option>
                              <option value="OCI">Oracle Cloud</option>
                              <option value="OTHER">Other cloud</option>
                            </select>
                          </label>
                        )}
                        <label className="field">
                          <span>Region or location (optional)</span>
                          <input
                            value={sourceRegion}
                            maxLength={64}
                            onChange={(event) =>
                              setSourceRegion(event.target.value)
                            }
                            placeholder="Chennai DC or ap-south-1"
                            autoComplete="off"
                          />
                        </label>
                        <label className="field">
                          <span>Registration method</span>
                          <select value="LOCAL_KUBECONFIG" disabled>
                            <option value="LOCAL_KUBECONFIG">
                              Local kubeconfig bootstrap — recommended
                            </option>
                          </select>
                          <small>
                            The kubeconfig remains on this computer and is never
                            uploaded to Navigan.
                          </small>
                        </label>
                      </div>
                      <button
                        type="button"
                        className="button button-primary"
                        disabled={sourceName.trim().length < 3 || sourceBusy}
                        onClick={() => void registerSourceCluster()}
                      >
                        {sourceBusy
                          ? "Registering source cluster…"
                          : "Register source cluster"}
                      </button>
                    </div>
                  )}
                </>
              )}

              {migration && selectedSource && (
                <div className={styles.connectionCard}>
                  <div>
                    <span className={styles.connectedDot} />
                    <strong>Source cluster registered</strong>
                  </div>
                  <dl>
                    <div>
                      <dt>Source cluster</dt>
                      <dd>{selectedSource.name}</dd>
                    </div>
                    <div>
                      <dt>Location</dt>
                      <dd>
                        {selectedSource.locationType.replaceAll("_", " ")}
                      </dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>
                        {sourceCatalogue
                          ? "Inventory ready"
                          : "Waiting for local connector setup"}
                      </dd>
                    </div>
                    <div>
                      <dt>Migration</dt>
                      <dd>{migration.migrationId}</dd>
                    </div>
                  </dl>

                  {sourceEnrollment && !sourceCatalogue && (
                    <div className={styles.bootstrapNotice}>
                      <strong>Secure enrollment prepared</strong>
                      <p>
                        Download the short-lived setup file and open it with the
                        approved Navigan bootstrap helper. The helper uses your
                        selected kubeconfig locally and deletes the setup file
                        after installation.
                      </p>
                      <button
                        type="button"
                        className="button button-primary"
                        onClick={downloadSourceBootstrap}
                      >
                        Download local connector setup
                      </button>
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
                      <dd>{sourceCatalogue.sourceKubernetesVersion}</dd>
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
                <p role="alert">Unable to retrieve the source catalogue.</p>
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
                  <strong>{namespaces.length} namespace selected</strong>
                  <span>Only sanitized metadata will be assessed.</span>
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
                  onChange={(event) => setTargetConnection(event.target.value)}
                >
                  <option value="">
                    {!targetEnvironment
                      ? "Select the target environment first"
                      : clustersQuery.isPending
                        ? "Loading eligible EKS clusters…"
                        : "Select an eligible EKS cluster"}
                  </option>
                  {targetClusters.map((cluster) => (
                    <option key={cluster.clusterId} value={cluster.clusterId}>
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
                  <span className={styles.previewBadge}>Backend record</span>
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
                  [
                    "Workloads and Kubernetes APIs",
                    "Versions, controllers and scheduling",
                  ],
                  [
                    "Networking and ingress",
                    "Services, DNS, ports and load balancers",
                  ],
                  [
                    "Storage and data",
                    "Claims, classes and persistence requirements",
                  ],
                  [
                    "Identity and security",
                    "RBAC, service accounts and policy requirements",
                  ],
                  [
                    "Capacity and architecture",
                    "CPU, memory, scaling and image architecture",
                  ],
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
                <div>
                  <span>Assessment</span>
                  <strong>{name}</strong>
                </div>
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
                <div>
                  <span>Namespaces</span>
                  <strong>{namespaces.join(", ")}</strong>
                </div>
                <div>
                  <span>Mode</span>
                  <strong>Read-only feasibility assessment</strong>
                </div>
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

          {step === 5 && scopeSaved && (
            <div className={styles.connectionCard}>
              {migration?.status === "INVENTORY_READY" && !assessment && (
                <>
                  <div>
                    <strong>Ready for detailed assessment</strong>
                  </div>
                  <p>
                    Assign detailed inventory collection to the connected
                    read-only source agent and generate the trusted report.
                  </p>
                  <button
                    type="button"
                    className="button button-primary"
                    disabled={assessmentBusy}
                    onClick={() => void startDetailedAssessment()}
                  >
                    {assessmentBusy
                      ? "Starting detailed assessment…"
                      : "Start detailed assessment"}
                  </button>
                </>
              )}

              {migration &&
                ["DISCOVERY_PENDING", "DISCOVERING", "ASSESSING"].includes(
                  migration.status,
                ) &&
                !assessment && (
                  <>
                    <div>
                      <span className={styles.connectedDot} />
                      <strong>Assessment assigned to source connector</strong>
                    </div>
                    <dl>
                      <div>
                        <dt>Source cluster</dt>
                        <dd>{selectedSource?.name ?? sourceClusterId}</dd>
                      </div>
                      <div>
                        <dt>Status</dt>
                        <dd>
                          {assessmentQuery.isError
                            ? "Unable to retrieve report"
                            : "Waiting for detailed inventory"}
                        </dd>
                      </div>
                    </dl>
                  </>
                )}

              {assessmentError && <p role="alert">{assessmentError}</p>}
            </div>
          )}

          {step === 5 && assessment && (
            <AssessmentReportCard report={assessment} />
          )}

          <footer className={styles.actions}>
            <div>
              <span>
                Step {step + 1} of {steps.length}
              </span>
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
