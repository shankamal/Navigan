"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  ArrowRight,
  Network,
  Settings,
  Clock3,
  Info,
  ShieldCheck,
} from "lucide-react";
import { customersService } from "@/modules/customer-management/services/customers";
import { normalizeApiError } from "@/shared/api/client";
import { migrations, sourceClusters } from "./service";
import { useSourceClusters } from "./hooks";
import type {
  CreateSourceClusterInput,
  Migration,
  SourceClusterRegistration,
  SourceEnrollment,
} from "./model";
import {
  validateSourceConnection,
  type ConnectionFieldErrors,
} from "./source-connection-validation";
import styles from "./source-connection-screen.module.css";

const journey = [
  "Source connection",
  "Discovery & assessment",
  "Migration scope",
  "Target & compatibility",
  "Review & approval",
  "Execute",
];

export function SourceConnectionScreen({
  initialDraftId,
}: { initialDraftId?: string } = {}) {
  const [name, setName] = useState("");
  const [customer, setCustomer] = useState("");
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<"REGISTER" | "EXISTING">("REGISTER");
  const [clusterName, setClusterName] = useState("");
  const [platform, setPlatform] = useState("SELF_MANAGED");
  const [distribution, setDistribution] = useState("Kubernetes (kubeadm)");
  const [location, setLocation] = useState<"CLOUD" | "ON_PREMISES" | "OTHER">(
    "CLOUD",
  );
  const [provider, setProvider] = useState("AWS");
  const [region, setRegion] = useState("");
  const [delivery, setDelivery] = useState<
    "AWS_SSM" | "MANUAL_HELM" | "GITOPS"
  >("AWS_SSM");
  const [account, setAccount] = useState("");
  const [instance, setInstance] = useState("");
  const [role, setRole] = useState("");
  const [kubeconfig, setKubeconfig] = useState("/etc/kubernetes/admin.conf");
  const [existingId, setExistingId] = useState("");
  const [source, setSource] = useState<SourceClusterRegistration | null>(null);
  const [draft, setDraft] = useState<Migration | null>(null);
  const [enrollment, setEnrollment] = useState<SourceEnrollment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<ConnectionFieldErrors>({});
  const formRef = useRef<HTMLFormElement>(null);
  const [notice, setNotice] = useState("");
  const [verifiedAt, setVerifiedAt] = useState("");
  const [checkingUntil, setCheckingUntil] = useState(0);
  const [commandId, setCommandId] = useState("");
  const [resumeId, setResumeId] = useState("");
  const writeKeys = useRef(new Map<string, string>());
  const locked = Boolean(source || draft || resumeId);

  function stableKey(operation: string, input: unknown) {
    const fingerprint = JSON.stringify([operation, input]);
    if (!writeKeys.current.has(fingerprint))
      writeKeys.current.set(fingerprint, crypto.randomUUID());
    return writeKeys.current.get(fingerprint)!;
  }

  const customersQuery = useQuery({
    queryKey: ["source-connection", "all-active-customers"],
    queryFn: async ({ signal }) => {
      const first = await customersService.list(
        { page: 0, pageSize: 100, status: "ACTIVE", sort: "name,asc" },
        signal,
      );
      const items = [...first.items];
      for (let page = 1; page < first.pagination.totalPages; page++) {
        const next = await customersService.list(
          { page, pageSize: 100, status: "ACTIVE", sort: "name,asc" },
          signal,
        );
        items.push(...next.items);
      }
      return items.filter((item) => item.status === "ACTIVE");
    },
    retry: false,
  });
  const sourcesQuery = useSourceClusters(customer);
  const connectedSources = (sourcesQuery.data?.items ?? []).filter(
    (item) => item.customerId === customer && item.status !== "REVOKED",
  );
  const customerOptions =
    customersQuery.data?.filter(
      (item) =>
        item.customerId === customer ||
        `${item.name} ${item.customerId}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    ) ?? [];

  useEffect(() => {
    const id =
      initialDraftId ||
      new URLSearchParams(window.location.search).get("draft");
    if (!id) return;
    let active = true;
    setResumeId(id);
    setBusy(true);
    migrations
      .get(id)
      .then(async (migration) => {
        if (
          migration.sourceConfiguration.discoveryMode !== "MANUAL" ||
          migration.status !== "DRAFT"
        )
          throw new Error("This is not a source connection draft.");
        const sourceId = String(
          migration.sourceConfiguration.sourceClusterId ?? "",
        );
        const registered = await sourceClusters.get(sourceId);
        if (registered.customerId !== migration.customerId)
          throw new Error("Source cluster customer mismatch.");
        if (!active) return;
        setName(migration.name);
        setCustomer(migration.customerId);
        setDraft(migration);
        setSource(registered);
        setMode("EXISTING");
        setExistingId(registered.sourceClusterId);
        setClusterName(registered.name);
        setDistribution(registered.distribution || "Kubernetes (kubeadm)");
        setLocation(registered.locationType);
        setProvider(registered.cloudProvider || "AWS");
        setRegion(registered.region || "");
        setDelivery(registered.deliveryMethod);
        setAccount(String(registered.deliveryConfiguration.accountId || ""));
        setInstance(
          String(registered.deliveryConfiguration.managedInstanceId || ""),
        );
        setRole(String(registered.deliveryConfiguration.roleArn || ""));
        setKubeconfig(
          String(
            registered.deliveryConfiguration.kubeconfigPath ||
              "/etc/kubernetes/admin.conf",
          ),
        );
        setNotice("Draft restored. Verify the source connection to continue.");
      })
      .catch((failure) => {
        if (active)
          setError(
            failure instanceof Error
              ? failure.message
              : "Unable to restore the draft.",
          );
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [initialDraftId]);

  function validateAction(action: "save" | "verify" | "continue") {
    const next = validateSourceConnection(
      {
        name,
        customer,
        mode,
        registered: Boolean(source),
        sourceId: source?.sourceClusterId || existingId,
        clusterName,
        platform,
        distribution,
        location,
        provider,
        region,
        delivery,
        account,
        instance,
        role,
        kubeconfig,
      },
      action,
      verifiedAt,
    );
    setFieldErrors(next);
    const first = Object.keys(next)[0];
    if (first) {
      requestAnimationFrame(() => {
        formRef.current
          ?.querySelector<HTMLElement>(`[name="${first}"]`)
          ?.focus();
        if (!formRef.current?.querySelector(`[name="${first}"]`))
          formRef.current
            ?.querySelector<HTMLElement>("[data-validation-summary]")
            ?.focus();
      });
      return false;
    }
    return true;
  }

  function continueToDiscovery() {
    if (!validateAction("continue")) return;
    setNotice(
      "Source connection verified. Source Discovery will be enabled in the next workflow increment.",
    );
  }

  async function verifyConnection() {
    if (busy || !validateAction("verify") || !source) return;
    setBusy(true);
    setError("");
    setVerifiedAt("");
    try {
      const current = await sourceClusters.get(source.sourceClusterId);
      setSource(current);
      const seen =
        typeof current.connectorLastSeenAt === "string"
          ? current.connectorLastSeenAt
          : "";
      const age = Date.now() - Date.parse(seen);
      if (current.status === "CONNECTED" && age >= -30_000 && age < 120_000) {
        setVerifiedAt(new Date().toISOString());
        setCheckingUntil(0);
        setNotice(
          "Source connector is connected and has a recent heartbeat. Kubernetes inventory and access checks belong to Source Discovery.",
        );
      } else {
        setNotice(
          "Waiting for a recent connector heartbeat. Check the connector installation, then verify again.",
        );
      }
    } catch (failure) {
      setError(normalizeApiError(failure).message);
      setCheckingUntil(0);
    } finally {
      setBusy(false);
    }
  }

  // Only poll during an installation requested here. Do not remount the form,
  // start discovery, fetch assessments, or poll forever on installation failure.
  useEffect(() => {
    if (!checkingUntil || !source) return;
    if (Date.now() >= checkingUntil) {
      setCheckingUntil(0);
      return;
    }
    const timer = setTimeout(() => {
      if (Date.now() >= checkingUntil) {
        setCheckingUntil(0);
        setNotice(
          "Automatic connection checks stopped after two minutes. Verify again or retry installation.",
        );
      } else void verifyConnection();
    }, 5_000);
    return () => clearTimeout(timer);
  }, [checkingUntil, source, busy]);

  async function deliver(registered: SourceClusterRegistration) {
    if (registered.deliveryMethod === "AWS_SSM") {
      const latest = await sourceClusters.get(registered.sourceClusterId);
      setSource(latest);
      const installation = await sourceClusters.install(
        latest.sourceClusterId,
        latest.version,
      );
      setCommandId(installation.commandId);
      setNotice(
        "Installation requested through AWS Systems Manager. Checking for the connector heartbeat…",
      );
      setCheckingUntil(Date.now() + 120_000);
    } else {
      if (
        !process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_API_BASE_URL ||
        !process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_IMAGE_REPOSITORY ||
        !process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_IMAGE_DIGEST
      )
        throw new Error(
          "The platform administrator must configure the connector API endpoint and pinned image before Helm or GitOps delivery is available.",
        );
      const latest = await sourceClusters.get(registered.sourceClusterId);
      setSource(latest);
      setEnrollment(
        await sourceClusters.enroll(latest.sourceClusterId, latest.version),
      );
      setNotice(
        "Download the enrollment configuration and install using your approved Helm or GitOps process. Then verify the connection.",
      );
    }
  }

  async function register(event: FormEvent) {
    event.preventDefault();
    if (busy || !validateAction("save")) return;
    const installNow =
      (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") !==
      "draft";
    setBusy(true);
    setError("");
    setVerifiedAt("");
    try {
      let registered = source;
      if (!registered && possibleMatch && mode === "REGISTER")
        throw new Error(
          "This SSM host and kubeconfig already have a registration for this customer. Use the existing source connection instead.",
        );
      if (!registered) {
        if (mode === "EXISTING") {
          registered = await sourceClusters.get(existingId);
          if (
            registered.customerId !== customer ||
            registered.status === "REVOKED"
          )
            throw new Error(
              "Select an available source registration belonging to this customer.",
            );
        } else {
          const input: CreateSourceClusterInput = {
            customerId: customer,
            name: clusterName.trim(),
            distribution,
            registrationMethod:
              delivery === "AWS_SSM"
                ? "PROVIDER_AUTOMATION"
                : delivery === "GITOPS"
                  ? "GITOPS"
                  : "LOCAL_KUBECONFIG",
            location: {
              type: location,
              cloudProvider:
                location === "CLOUD" ? (provider as "AWS") : undefined,
              region: region.trim(),
            },
            delivery: {
              method: delivery,
              awsSsm:
                delivery === "AWS_SSM"
                  ? {
                      accountId: account.trim(),
                      region: region.trim(),
                      managedInstanceId: instance.trim(),
                      roleArn: role.trim() || undefined,
                      kubeconfigPath: kubeconfig.trim(),
                    }
                  : undefined,
            },
          };
          registered = await sourceClusters.create(
            input,
            stableKey("source", input),
          );
        }
        setSource(registered);
      }
      if (!draft) {
        const input = {
          customerId: customer,
          name: name.trim(),
          source: {
            platform: "SELF_MANAGED_KUBERNETES" as const,
            sourceClusterId: registered.sourceClusterId,
            accessMode: "READ_ONLY_CONNECTOR" as const,
            discoveryMode: "MANUAL" as const,
          },
          scope: {
            namespaces: [],
            excludeNamespaces: [
              "kube-system",
              "kube-public",
              "kube-node-lease",
            ],
            includeClusterScopedResources: false as const,
            includePersistentData: false as const,
          },
        };
        const created = await migrations.create(
          input,
          stableKey("draft", input),
        );
        setDraft(created);
        const url = new URL(window.location.href);
        url.searchParams.set("draft", created.migrationId);
        window.history.replaceState(null, "", url);
      }
      if (installNow && mode === "REGISTER" && !commandId && !enrollment)
        await deliver(registered);
      else
        setNotice(
          "Assessment draft saved. Verify the source connector connection.",
        );
    } catch (failure) {
      setError(
        failure instanceof Error && !("status" in failure)
          ? failure.message
          : normalizeApiError(failure).message,
      );
    } finally {
      setBusy(false);
    }
  }

  async function retryDelivery() {
    if (!source || busy || checkingUntil) return;
    setBusy(true);
    setError("");
    setVerifiedAt("");
    try {
      await deliver(source);
    } catch (failure) {
      setError(normalizeApiError(failure).message);
    } finally {
      setBusy(false);
    }
  }

  function downloadEnrollment() {
    if (!enrollment || !source) return;
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            {
              sourceClusterId: source.sourceClusterId,
              enrollmentToken: enrollment.enrollmentToken,
              enrollmentExpiresAt: enrollment.expiresAt,
              apiBaseUrl:
                process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_API_BASE_URL,
              imageRepository:
                process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_IMAGE_REPOSITORY,
              imageDigest:
                process.env.NEXT_PUBLIC_MIGRATION_CONNECTOR_IMAGE_DIGEST,
            },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `navigan-source-enrollment-${source.sourceClusterId}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const displaySource =
    source ??
    connectedSources.find((item) => item.sourceClusterId === existingId);
  const possibleMatch =
    !locked && mode === "REGISTER"
      ? (sourcesQuery.data?.items ?? []).find((item) => {
          if (item.customerId !== customer || item.status === "REVOKED")
            return false;
          const config = item.deliveryConfiguration ?? {};
          return (
            delivery === "AWS_SSM" &&
            account.trim() &&
            instance.trim() &&
            region.trim() &&
            config.accountId === account.trim() &&
            config.managedInstanceId === instance.trim() &&
            config.region === region.trim() &&
            config.kubeconfigPath === kubeconfig.trim()
          );
        })
      : undefined;
  const reuseCandidate =
    possibleMatch ??
    (!locked && mode === "REGISTER"
      ? connectedSources.find(
          (item) =>
            clusterName.trim() &&
            item.name.toLowerCase() === clusterName.trim().toLowerCase(),
        )
      : undefined);
  function chooseExisting(item: SourceClusterRegistration) {
    setMode("EXISTING");
    setFieldErrors({});
    setExistingId(item.sourceClusterId);
    setError("");
    setVerifiedAt("");
  }
  const canSave = !busy && !draft && !resumeId;

  return (
    <div className={styles.screen}>
      <header className={styles.heading}>
        <div className={styles.titleGroup}>
          <Network size={25} aria-hidden="true" />
          <div>
            <h1>New Migration Assessment</h1>
            <p>Connect a source cluster to begin.</p>
          </div>
        </div>
        <Link href="/migrations" className={styles.back}>
          <ArrowLeft size={15} />
          Back to assessments
        </Link>
      </header>
      <ol className={styles.journey} aria-label="Migration workflow">
        {journey.map((label, index) => (
          <li key={label} aria-current={index === 0 ? "step" : undefined}>
            <span>{index + 1}</span>
            {label}
          </li>
        ))}
      </ol>
      <form
        onChange={(event) => {
          const target: EventTarget = event.target;
          if (!(
            target instanceof HTMLInputElement ||
            target instanceof HTMLSelectElement
          ))
            return;
          const key = target.name as keyof ConnectionFieldErrors;
          if (key && fieldErrors[key])
            setFieldErrors((current) => ({ ...current, [key]: undefined }));
        }}
        ref={formRef}
        noValidate
        onSubmit={register}
        className={styles.form}
      >
        {Object.values(fieldErrors).some(Boolean) && (
          <div
            className={styles.validationSummary}
            role="alert"
            tabIndex={-1}
            data-validation-summary
          >
            <strong>Check the highlighted fields</strong>
            <ul>
              {Object.entries(fieldErrors)
                .filter(([, message]) => Boolean(message))
                .map(([key, message]) => (
                  <li key={key} id={`source-error-${key}`}>
                    {message}
                  </li>
                ))}
            </ul>
          </div>
        )}
        <section
          className={`${styles.panel} ${styles.identity}`}
          aria-labelledby="assessment-details-title"
        >
          <div className={styles.panelHeading}>
            <div>
              <h2 id="assessment-details-title">Assessment identity</h2>
              <p>Provide a name for this assessment and select the customer.</p>
            </div>
          </div>
          <fieldset
            disabled={Boolean(draft) || busy || Boolean(resumeId)}
            className={styles.identityGrid}
          >
            <label>
              Assessment name <span>*</span>
              <input
                required
                minLength={8}
                maxLength={100}
                name="name"
                title="Use 8–100 characters to identify this migration assessment."
                aria-invalid={Boolean(fieldErrors.name)}
                aria-errormessage={
                  fieldErrors.name ? "source-error-name" : undefined
                }
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Payments migration"
              />
              <small>
                A unique name for this assessment. {name.length}/100 characters.
              </small>
            </label>
            <div className={styles.customerField}>
              <label>
                Active customer <span>*</span>
                <select
                  required
                  name="customer"
                  title="Select an active customer within your access. Cluster connections belong to that customer."
                  aria-invalid={Boolean(fieldErrors.customer)}
                  aria-errormessage={
                    fieldErrors.customer ? "source-error-customer" : undefined
                  }
                  value={customer}
                  disabled={
                    locked || customersQuery.isPending || customersQuery.isError
                  }
                  onChange={(e) => {
                    setCustomer(e.target.value);
                    setExistingId("");
                    setSearch("");
                  }}
                >
                  <option value="">
                    {customersQuery.isPending
                      ? "Loading active customers…"
                      : "Select an active customer"}
                  </option>
                  {customerOptions.map((item) => (
                    <option key={item.customerId} value={item.customerId}>
                      {item.name}
                    </option>
                  ))}
                </select>
                <small>Select the customer that owns this migration.</small>
              </label>
              <details className={styles.customerSearch}>
                <summary>Find customer by name or ID</summary>
                <label>
                  Search active customers
                  <input
                    disabled={locked}
                    type="search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Customer name or ID"
                  />
                </label>
              </details>
            </div>
          </fieldset>
          {customersQuery.isError && (
            <p role="alert" className={styles.error}>
              Unable to load customers.{" "}
              <button type="button" onClick={() => customersQuery.refetch()}>
                Retry customer list
              </button>
            </p>
          )}
          {customersQuery.isSuccess && !customersQuery.data.length && (
            <p>No active customers are available within your access.</p>
          )}
          {reuseCandidate && (
            <div className={styles.reuseBanner}>
              <img src="/logos/kubernetes.svg" alt="" />
              <div>
                <strong>{reuseCandidate.name}</strong>
                <span>
                  <CheckCircle2 size={14} />
                  Existing registration available
                </span>
                <p>
                  {possibleMatch
                    ? "The same SSM host and kubeconfig are already registered for this customer."
                    : "A cluster with this name is already registered. Check its details before registering another connection."}
                </p>
              </div>
              <button
                type="button"
                onClick={() => chooseExisting(reuseCandidate)}
              >
                Reuse connection <ArrowRight size={15} />
              </button>
            </div>
          )}
          {displaySource && (
            <div className={styles.reuseBanner}>
              <img src="/logos/kubernetes.svg" alt="" />
              <div>
                <strong>{displaySource.name}</strong>
                <span>
                  <CheckCircle2 size={14} />
                  {mode === "EXISTING"
                    ? "Existing connection selected"
                    : "Source cluster registered"}
                </span>
                <p>
                  {mode === "EXISTING"
                    ? "The existing connector will be reused. No additional installation is required."
                    : "This cluster registration is linked to your assessment."}
                </p>
              </div>
              <span className={styles.badge}>
                {verifiedAt
                  ? "Connected"
                  : displaySource.status === "CONNECTED"
                    ? "Verify connection"
                    : "Awaiting connection"}
              </span>
            </div>
          )}
        </section>
        <div className={styles.columns}>
          <section
            className={styles.panel}
            aria-labelledby="source-cluster-title"
          >
            <div className={styles.panelHeading}>
              <Network size={20} />
              <div>
                <h2 id="source-cluster-title">
                  Source cluster{" "}
                  <span
                    className={styles.tooltip}
                    tabIndex={0}
                    role="img"
                    aria-label="Register once per customer-owned cluster. Reuse its connector across assessments."
                  >
                    <Info size={13} />
                    <span role="tooltip">
                      Register once per customer-owned cluster. Reuse its
                      connector across assessments.
                    </span>
                  </span>
                </h2>
                <p>Provide details about the source Kubernetes cluster.</p>
              </div>
              <fieldset
                disabled={locked || busy}
                className={styles.segment}
                role="radiogroup"
                aria-label="Source registration"
              >
                <label className={mode === "EXISTING" ? styles.selected : ""}>
                  <input
                    type="radio"
                    name="source-mode"
                    aria-label="Use a connected source cluster"
                    checked={mode === "EXISTING"}
                    onChange={() => {
                      setMode("EXISTING");
                      setFieldErrors({});
                    }}
                  />
                  Use connected cluster
                </label>
                <label className={mode === "REGISTER" ? styles.selected : ""}>
                  <input
                    type="radio"
                    name="source-mode"
                    aria-label="Register a new source cluster"
                    checked={mode === "REGISTER"}
                    onChange={() => {
                      setMode("REGISTER");
                      setFieldErrors({});
                    }}
                  />
                  Register new cluster
                </label>
              </fieldset>
            </div>
            {mode === "EXISTING" ? (
              <>
                <label>
                  Connected source cluster <span>*</span>
                  <select
                    required
                    disabled={locked || !customer || busy}
                    name="sourceId"
                    title="Reuse a connected cluster belonging to this customer. No additional connector is installed."
                    aria-invalid={Boolean(fieldErrors.sourceId)}
                    value={existingId || source?.sourceClusterId || ""}
                    onChange={(e) => {
                      setExistingId(e.target.value);
                      setVerifiedAt("");
                    }}
                  >
                    <option value="">
                      {!customer
                        ? "Select a customer first"
                        : "Select a connected source cluster"}
                    </option>
                    {connectedSources.map((item) => (
                      <option
                        key={item.sourceClusterId}
                        value={item.sourceClusterId}
                      >
                        {item.name} · {item.region ?? item.locationType}
                      </option>
                    ))}
                    {source &&
                      !connectedSources.some(
                        (item) =>
                          item.sourceClusterId === source.sourceClusterId,
                      ) && (
                        <option value={source.sourceClusterId}>
                          {source.name}
                        </option>
                      )}
                  </select>
                  <small>
                    Reuse a customer connection across multiple assessments.
                  </small>
                </label>
                {sourcesQuery.isError && (
                  <p role="alert" className={styles.error}>
                    Unable to load source clusters.{" "}
                    <button
                      type="button"
                      onClick={() => sourcesQuery.refetch()}
                    >
                      Retry
                    </button>
                  </p>
                )}
                {customer &&
                  sourcesQuery.isSuccess &&
                  !connectedSources.length &&
                  !source && (
                    <p className={styles.empty}>
                      No connected clusters found. Register a new source
                      cluster.
                    </p>
                  )}
                {displaySource && (
                  <dl className={styles.facts}>
                    <div>
                      <dt>Source platform</dt>
                      <dd>Self-managed Kubernetes</dd>
                    </div>
                    <div>
                      <dt>Kubernetes distribution</dt>
                      <dd>{displaySource.distribution ?? "Kubernetes"}</dd>
                    </div>
                    <div>
                      <dt>Cluster location</dt>
                      <dd>
                        {displaySource.locationType === "CLOUD"
                          ? "Cloud virtual machines"
                          : displaySource.locationType === "ON_PREMISES"
                            ? "Customer data centre"
                            : "Other"}
                      </dd>
                    </div>
                    <div>
                      <dt>Cloud provider</dt>
                      <dd>{displaySource.cloudProvider ?? "Not applicable"}</dd>
                    </div>
                    <div>
                      <dt>Region / site</dt>
                      <dd>{displaySource.region ?? "Not specified"}</dd>
                    </div>
                  </dl>
                )}
              </>
            ) : (
              <fieldset disabled={locked || busy} className={styles.grid}>
                <label>
                  Source cluster name <span>*</span>
                  <input
                    required
                    minLength={3}
                    maxLength={100}
                    pattern="[A-Za-z0-9][A-Za-z0-9._ -]*"
                    name="clusterName"
                    title="A friendly name for the source Kubernetes cluster. Register a cluster once and reuse its connection."
                    aria-invalid={Boolean(fieldErrors.clusterName)}
                    aria-errormessage={
                      fieldErrors.clusterName
                        ? "source-error-clusterName"
                        : undefined
                    }
                    value={clusterName}
                    onChange={(e) => setClusterName(e.target.value)}
                    placeholder="navigan-migration-lab"
                  />
                  <small>Name of your Kubernetes cluster.</small>
                </label>
                <label>
                  Source platform <span>*</span>
                  <select
                    required
                    name="platform"
                    title="Select the source platform. Kubernetes installed on EC2 is Self-managed Kubernetes."
                    aria-invalid={Boolean(fieldErrors.platform)}
                    aria-errormessage={
                      fieldErrors.platform ? "source-error-platform" : undefined
                    }
                    value={platform}
                    onChange={(e) => setPlatform(e.target.value)}
                  >
                    <option value="SELF_MANAGED">
                      Self-managed Kubernetes
                    </option>
                    <option value="AWS">AWS</option>
                    <option disabled>Azure — planned</option>
                    <option disabled>Google Cloud — planned</option>
                    <option disabled>Red Hat OpenShift — planned</option>
                    <option disabled>Other — planned</option>
                  </select>
                  <small>Where your Kubernetes cluster is hosted.</small>
                </label>
                <label>
                  Kubernetes distribution <span>*</span>
                  <select
                    required
                    name="distribution"
                    title="Select the Kubernetes distribution or installation method."
                    aria-invalid={Boolean(fieldErrors.distribution)}
                    aria-errormessage={
                      fieldErrors.distribution
                        ? "source-error-distribution"
                        : undefined
                    }
                    value={distribution}
                    onChange={(e) => setDistribution(e.target.value)}
                  >
                    {[
                      "Kubernetes (kubeadm)",
                      "K3s",
                      "RKE2",
                      "Other self-managed Kubernetes",
                    ].map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                  <small>Kubernetes distribution or installer.</small>
                </label>
                <label>
                  Cluster location <span>*</span>
                  <select
                    required
                    name="location"
                    title="Choose customer data centre, cloud virtual machines or another location."
                    aria-invalid={Boolean(fieldErrors.location)}
                    aria-errormessage={
                      fieldErrors.location ? "source-error-location" : undefined
                    }
                    value={location}
                    onChange={(e) => {
                      const next = e.target.value as typeof location;
                      setLocation(next);
                      if (next !== "CLOUD") setDelivery("MANUAL_HELM");
                    }}
                  >
                    <option value="CLOUD">Cloud virtual machines</option>
                    <option value="ON_PREMISES">
                      Customer data centre / On-premises
                    </option>
                    <option value="OTHER">Other location</option>
                  </select>
                  <small>Location of the source infrastructure.</small>
                </label>
                {location === "CLOUD" && (
                  <label>
                    Cloud provider <span>*</span>
                    <select
                      required
                      name="provider"
                      title="Select the provider hosting the source cluster virtual machines."
                      aria-invalid={Boolean(fieldErrors.provider)}
                      aria-errormessage={
                        fieldErrors.provider
                          ? "source-error-provider"
                          : undefined
                      }
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                    >
                      <option value="AWS">AWS EC2</option>
                      <option disabled>Azure — planned</option>
                      <option disabled>Google Cloud — planned</option>
                      <option disabled>OCI — planned</option>
                      <option disabled>Other cloud — planned</option>
                    </select>
                    <small>Kubernetes on EC2 is self-managed.</small>
                  </label>
                )}
                <label>
                  {location === "CLOUD"
                    ? "AWS region"
                    : "Region or site location"}{" "}
                  <span>*</span>
                  <input
                    required
                    maxLength={64}
                    name="region"
                    title="AWS region such as ap-south-1, or the site name for an on-premises cluster."
                    aria-invalid={Boolean(fieldErrors.region)}
                    aria-errormessage={
                      fieldErrors.region ? "source-error-region" : undefined
                    }
                    value={region}
                    onChange={(e) => setRegion(e.target.value)}
                    placeholder={
                      location === "CLOUD" ? "ap-south-1" : "Chennai DC1"
                    }
                  />
                  <small>
                    {location === "CLOUD"
                      ? "AWS region of the source cluster."
                      : "Customer site or data-centre location."}
                  </small>
                </label>
              </fieldset>
            )}
            {platform === "AWS" && mode === "REGISTER" && (
              <p className={styles.warning}>
                Managed AWS source paths are planned. For Kubernetes on EC2,
                select Self-managed Kubernetes.
              </p>
            )}
          </section>
          <section
            className={styles.panel}
            aria-labelledby="connector-delivery-title"
          >
            <div className={styles.panelHeading}>
              <Settings size={20} />
              <div>
                <h2 id="connector-delivery-title">
                  Connector delivery{" "}
                  <span
                    className={styles.tooltip}
                    tabIndex={0}
                    role="img"
                    aria-label="SSM installs remotely. Helm and GitOps provide enrollment configuration for your cluster administrator."
                  >
                    <Info size={13} />
                    <span role="tooltip">
                      SSM installs remotely. Helm and GitOps provide enrollment
                      configuration for your cluster administrator.
                    </span>
                  </span>
                </h2>
                <p>
                  {mode === "EXISTING"
                    ? "Use the connector already registered for this cluster."
                    : "Specify how the connector will be deployed to your source cluster."}
                </p>
              </div>
            </div>
            {mode === "EXISTING" ? (
              <>
                {displaySource ? (
                  <>
                    <dl className={styles.facts}>
                      <div>
                        <dt>Connector delivery</dt>
                        <dd>
                          {displaySource.deliveryMethod === "AWS_SSM"
                            ? "AWS Systems Manager"
                            : displaySource.deliveryMethod === "GITOPS"
                              ? "GitOps"
                              : "Helm configuration"}
                        </dd>
                      </div>
                      {displaySource.deliveryMethod === "AWS_SSM" &&
                        [
                          ["AWS account ID", "accountId"],
                          ["SSM managed instance ID", "managedInstanceId"],
                          ["Kubeconfig path", "kubeconfigPath"],
                        ].map(([label, key]) => (
                          <div key={key}>
                            <dt>{label}</dt>
                            <dd>
                              {String(
                                displaySource.deliveryConfiguration?.[key] ??
                                  "Not specified",
                              )}
                            </dd>
                          </div>
                        ))}
                    </dl>
                    <p className={styles.reuseNote}>
                      <ShieldCheck size={18} />
                      Existing connector will be reused. No additional pod
                      installation.
                    </p>
                  </>
                ) : (
                  <p className={styles.empty}>
                    Select a connected source cluster to view its connection
                    details.
                  </p>
                )}
              </>
            ) : (
              <fieldset disabled={locked || busy}>
                <label>
                  Connector delivery method <span>*</span>
                  <select
                    required
                    name="delivery"
                    title="Choose AWS Systems Manager, a Helm configuration download or GitOps delivery."
                    aria-invalid={Boolean(fieldErrors.delivery)}
                    aria-errormessage={
                      fieldErrors.delivery ? "source-error-delivery" : undefined
                    }
                    value={delivery}
                    onChange={(e) =>
                      setDelivery(e.target.value as typeof delivery)
                    }
                  >
                    <option
                      value="AWS_SSM"
                      disabled={location !== "CLOUD" || provider !== "AWS"}
                    >
                      AWS Systems Manager
                    </option>
                    <option value="MANUAL_HELM">
                      Download Helm configuration
                    </option>
                    <option value="GITOPS">GitOps delivery</option>
                  </select>
                  <small>
                    {delivery === "AWS_SSM"
                      ? "Use SSM to deploy and manage the connector."
                      : "Generate configuration for your approved deployment process."}
                  </small>
                </label>
                {delivery === "AWS_SSM" ? (
                  <>
                    <div className={styles.grid}>
                      <label>
                        AWS account ID <span>*</span>
                        <input
                          required
                          inputMode="numeric"
                          pattern="[0-9]{12}"
                          maxLength={12}
                          name="account"
                          title="Exactly 12 digits for the AWS account that owns the managed source host."
                          aria-invalid={Boolean(fieldErrors.account)}
                          aria-errormessage={
                            fieldErrors.account
                              ? "source-error-account"
                              : undefined
                          }
                          value={account}
                          onChange={(e) => setAccount(e.target.value)}
                          placeholder="123456789012"
                        />
                        <small>12-digit source AWS account ID.</small>
                      </label>
                      <label>
                        SSM managed instance ID <span>*</span>
                        <input
                          required
                          pattern="(i-[0-9a-f]{8,17}|mi-[A-Za-z0-9-]+)"
                          name="instance"
                          title="The SSM managed control-plane or administration host with Kubernetes API access."
                          aria-invalid={Boolean(fieldErrors.instance)}
                          aria-errormessage={
                            fieldErrors.instance
                              ? "source-error-instance"
                              : undefined
                          }
                          value={instance}
                          onChange={(e) => setInstance(e.target.value)}
                          placeholder="i-0123456789abcdef0"
                        />
                        <small>
                          Control-plane or administration host with cluster
                          access.
                        </small>
                      </label>
                      <label className={styles.full}>
                        Kubeconfig path on the source host <span>*</span>
                        <input
                          required
                          pattern="/[A-Za-z0-9._/-]+"
                          maxLength={512}
                          name="kubeconfig"
                          title="An absolute path on the source host, not a path on your laptop."
                          aria-invalid={Boolean(fieldErrors.kubeconfig)}
                          aria-errormessage={
                            fieldErrors.kubeconfig
                              ? "source-error-kubeconfig"
                              : undefined
                          }
                          value={kubeconfig}
                          onChange={(e) => setKubeconfig(e.target.value)}
                        />
                        <small>
                          Path on the managed host, not your laptop.
                        </small>
                      </label>
                    </div>
                    <details className={styles.advanced}>
                      <summary>
                        Advanced <small>(optional)</small>
                        <span>Cross-account role</span>
                      </summary>
                      <label>
                        Cross-account role ARN
                        <input
                          pattern="arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+"
                          maxLength={2048}
                          name="role"
                          title="Optional for same-account access; supply the approved IAM role ARN when using a cross-account role."
                          aria-invalid={Boolean(fieldErrors.role)}
                          aria-errormessage={
                            fieldErrors.role ? "source-error-role" : undefined
                          }
                          value={role}
                          onChange={(e) => setRole(e.target.value)}
                          placeholder="arn:aws:iam::123456789012:role/NaviganSourceConnector"
                        />
                        <small>Required when using a cross-account role.</small>
                      </label>
                    </details>
                  </>
                ) : (
                  <p className={styles.methodNote}>
                    Download the short-lived enrollment configuration and apply
                    the approved Helm chart
                    {delivery === "GITOPS"
                      ? " through your GitOps repository"
                      : ""}
                    . No kubeconfig contents are uploaded.
                  </p>
                )}
              </fieldset>
            )}
          </section>
        </div>
        <section
          className={`${styles.panel} ${styles.verification}`}
          aria-label="Connection status"
        >
          <div className={styles.verificationHeading}>
            <CheckCircle2 size={19} />
            <div>
              <h2>Connection verification</h2>
              <p>
                {verifiedAt
                  ? "Connected · recent connector heartbeat verified"
                  : "Verify your source connector connection. Kubernetes access is checked during discovery."}
              </p>
            </div>
            <p className={styles.context}>
              Source: {displaySource?.name || clusterName || "Not selected"}{" "}
              <span>·</span>{" "}
              {displaySource?.region || region || "Region not selected"}
            </p>
          </div>
          <div className={styles.verificationBottom}>
            <ol className={styles.checks}>
              <li>
                <CheckCircle2
                  size={19}
                  className={source ? styles.complete : ""}
                />
                <div>
                  <strong>Cluster registered</strong>
                  <small>
                    {source
                      ? "Assessment linked to source"
                      : "Register or select source"}
                  </small>
                </div>
              </li>
              <li>
                <Clock3
                  size={19}
                  className={verifiedAt ? styles.complete : ""}
                />
                <div>
                  <strong>Connector heartbeat</strong>
                  <small>
                    {verifiedAt
                      ? "Recent heartbeat verified"
                      : checkingUntil
                        ? "Checking connection…"
                        : "Awaiting verification"}
                  </small>
                </div>
              </li>
              <li>
                <ShieldCheck size={19} />
                <div>
                  <strong>Kubernetes access</strong>
                  <small>Validated during discovery</small>
                </div>
              </li>
            </ol>
            <div className={styles.actions}>
              {!draft && (
                <>
                  <button
                    type="submit"
                    name="intent"
                    value="draft"
                    disabled={!canSave}
                  >
                    Save draft
                  </button>
                  <button
                    className={styles.primary}
                    type="submit"
                    name="intent"
                    value="connect"
                    disabled={!canSave}
                  >
                    {busy
                      ? "Saving connection…"
                      : mode === "REGISTER"
                        ? "Connect source"
                        : "Use source connection"}
                  </button>
                </>
              )}
              {draft && source && (
                <>
                  <button
                    className={styles.primary}
                    type="button"
                    onClick={verifyConnection}
                    disabled={busy}
                  >
                    {busy ? "Checking connection…" : "Verify connection"}
                  </button>
                  {!verifiedAt &&
                    !checkingUntil &&
                    (mode === "REGISTER" || source.status !== "CONNECTED") && (
                      <button
                        type="button"
                        onClick={retryDelivery}
                        disabled={busy}
                      >
                        {source.deliveryMethod === "AWS_SSM"
                          ? commandId
                            ? "Retry installation"
                            : "Install connector"
                          : "Generate enrollment configuration"}
                      </button>
                    )}
                </>
              )}
              <button
                type="button"
                disabled
                onClick={continueToDiscovery}
                title="Requires a saved assessment, a recently verified source connection, and an available Source Discovery screen."
              >
                Continue to discovery <ArrowRight size={15} />
              </button>
            </div>
          </div>
          <div aria-live="polite" className={styles.feedback}>
            {notice && <p>{notice}</p>}
            {verifiedAt && (
              <small>Verified {new Date(verifiedAt).toLocaleString()}</small>
            )}
          </div>
          {error && (
            <p role="alert" className={styles.error}>
              {error}
            </p>
          )}
          {enrollment && (
            <p>
              <button type="button" onClick={downloadEnrollment}>
                Download enrollment configuration
              </button>
              <small>
                Expires {new Date(enrollment.expiresAt).toLocaleString()}. Keep
                this credential private.
              </small>
            </p>
          )}
          {(draft || commandId) && (
            <details className={styles.technical}>
              <summary>Connection reference</summary>
              {draft && <p>Assessment ID: {draft.migrationId}</p>}
              {source && <p>Source ID: {source.sourceClusterId}</p>}
              {commandId && <p>SSM command: {commandId}</p>}
            </details>
          )}
        </section>
      </form>
    </div>
  );
}
