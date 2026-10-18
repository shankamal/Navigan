"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  PlugZap,
  Server,
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
    (item) => item.customerId === customer && item.status === "CONNECTED",
  );
  const selectedCustomer = customersQuery.data?.find(
    (item) => item.customerId === customer,
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

  async function verifyConnection() {
    if (!source || busy) return;
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
    if (busy || platform !== "SELF_MANAGED") return;
    setBusy(true);
    setError("");
    setVerifiedAt("");
    try {
      let registered = source;
      if (!registered) {
        if (mode === "EXISTING") {
          registered = await sourceClusters.get(existingId);
          if (
            registered.customerId !== customer ||
            registered.status !== "CONNECTED"
          )
            throw new Error(
              "Select a connected cluster belonging to this customer.",
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
      if (mode === "REGISTER" && !commandId && !enrollment)
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

  return (
    <main className={styles.screen}>
      <header className={styles.heading}>
        <div>
          <p className={styles.eyebrow}>MIGRATION / NEW ASSESSMENT</p>
          <h1>New Migration Assessment</h1>
          <p>
            Connect your source cluster to begin an application migration
            assessment.
          </p>
        </div>
        <Link href="/migrations" className={styles.back}>
          <ArrowLeft size={16} /> Back to migrations
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
      <div className={styles.layout}>
        <form onSubmit={register} className={styles.form}>
          <section className={styles.section}>
            <div className={styles.sectionTitle}>
              <span>01</span>
              <div>
                <h2>Assessment details</h2>
                <p>Give this migration its own name and customer context.</p>
              </div>
            </div>
            <fieldset disabled={Boolean(draft) || busy || Boolean(resumeId)}>
              <div className={styles.grid}>
                <label>
                  Assessment name <span>*</span>
                  <input
                    required
                    minLength={8}
                    maxLength={100}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Retail Payments – Kubernetes to EKS"
                  />
                  <small>8–100 characters · {name.length}/100</small>
                </label>
                <div>
                  <label htmlFor="customer-search">
                    Find an active customer
                    <input
                      disabled={locked}
                      id="customer-search"
                      type="search"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search by customer name or ID"
                    />
                  </label>
                  <label htmlFor="source-customer">
                    Active customer <span>*</span>
                    <select
                      id="source-customer"
                      required
                      value={customer}
                      onChange={(e) => {
                        setCustomer(e.target.value);
                        setExistingId("");
                      }}
                      disabled={
                        locked ||
                        customersQuery.isPending ||
                        customersQuery.isError
                      }
                    >
                      <option value="">
                        {customersQuery.isPending
                          ? "Loading active customers…"
                          : "Select an active customer"}
                      </option>
                      {customerOptions.map((item) => (
                        <option key={item.customerId} value={item.customerId}>
                          {item.name} · {item.customerId}
                        </option>
                      ))}
                    </select>
                    <small>
                      Only active customers within your access are listed.
                    </small>
                  </label>
                </div>
              </div>
            </fieldset>
            {customersQuery.isError && (
              <p role="alert">
                Unable to load customers.{" "}
                <button type="button" onClick={() => customersQuery.refetch()}>
                  Retry customer list
                </button>
              </p>
            )}
            {customersQuery.isSuccess && !customersQuery.data.length && (
              <p>No active customers are available within your access.</p>
            )}
          </section>
          <section className={styles.section}>
            <div className={styles.sectionTitle}>
              <span>02</span>
              <div>
                <h2>Source cluster</h2>
                <p>
                  Register once per cluster. Reuse the connection across
                  assessments.
                </p>
              </div>
            </div>
            <fieldset disabled={locked || busy}>
              <div
                className={styles.choices}
                role="radiogroup"
                aria-label="Source registration"
              >
                <label className={mode === "REGISTER" ? styles.selected : ""}>
                  <input
                    type="radio"
                    name="source-mode"
                    checked={mode === "REGISTER"}
                    onChange={() => setMode("REGISTER")}
                  />
                  <Server size={20} />
                  <strong>Register a new source cluster</strong>
                  <small>Establish a new cluster connection</small>
                </label>
                <label className={mode === "EXISTING" ? styles.selected : ""}>
                  <input
                    type="radio"
                    name="source-mode"
                    checked={mode === "EXISTING"}
                    onChange={() => setMode("EXISTING")}
                  />
                  <PlugZap size={20} />
                  <strong>Use a connected source cluster</strong>
                  <small>Reuse an existing customer connection</small>
                </label>
              </div>
            </fieldset>
            {mode === "EXISTING" ? (
              <label>
                Connected source cluster <span>*</span>
                <select
                  required
                  disabled={locked || !customer || busy}
                  value={existingId || source?.sourceClusterId || ""}
                  onChange={(e) => setExistingId(e.target.value)}
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
                      {item.name} · {item.distribution ?? "Kubernetes"} ·{" "}
                      {item.region ?? item.locationType}
                    </option>
                  ))}
                </select>
                {customer &&
                  sourcesQuery.isSuccess &&
                  !connectedSources.length && (
                    <small>
                      No connected clusters found. Register a new source
                      cluster.
                    </small>
                  )}
                {sourcesQuery.isError && (
                  <small role="alert">
                    Unable to load source clusters.{" "}
                    <button
                      type="button"
                      onClick={() => sourcesQuery.refetch()}
                    >
                      Retry
                    </button>
                  </small>
                )}
              </label>
            ) : (
              <fieldset disabled={locked || busy}>
                <div className={styles.grid}>
                  <label>
                    Source cluster name <span>*</span>
                    <input
                      required
                      minLength={3}
                      maxLength={100}
                      pattern="[A-Za-z0-9][A-Za-z0-9._ -]*"
                      value={clusterName}
                      onChange={(e) => setClusterName(e.target.value)}
                      placeholder="payments-source-cluster"
                    />
                  </label>
                  <label>
                    Source platform <span>*</span>
                    <select
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
                  </label>
                  <label>
                    Kubernetes distribution <span>*</span>
                    <select
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
                  </label>
                  <label>
                    Cluster location <span>*</span>
                    <select
                      value={location}
                      onChange={(e) => {
                        const next = e.target.value as typeof location;
                        setLocation(next);
                        if (next !== "CLOUD") setDelivery("MANUAL_HELM");
                      }}
                    >
                      <option value="ON_PREMISES">
                        Customer data centre / On-premises
                      </option>
                      <option value="CLOUD">Cloud virtual machines</option>
                      <option value="OTHER">Other location</option>
                    </select>
                  </label>
                  {location === "CLOUD" && (
                    <label>
                      Cloud provider <span>*</span>
                      <select
                        value={provider}
                        onChange={(e) => setProvider(e.target.value)}
                      >
                        <option value="AWS">AWS — EC2 instances</option>
                        <option disabled>Azure — planned</option>
                        <option disabled>Google Cloud — planned</option>
                        <option disabled>OCI — planned</option>
                        <option disabled>Other cloud — planned</option>
                      </select>
                      <small>
                        Kubernetes on EC2 remains a self-managed cluster.
                      </small>
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
                      value={region}
                      onChange={(e) => setRegion(e.target.value)}
                      placeholder={
                        location === "CLOUD" ? "ap-south-1" : "Chennai DC1"
                      }
                    />
                  </label>
                </div>
                {platform === "AWS" && (
                  <p className={styles.warning}>
                    AWS managed services such as EKS and ECS will be added as
                    source paths later. For Kubernetes installed on EC2, select
                    Self-managed Kubernetes and AWS as the cloud provider.
                  </p>
                )}
              </fieldset>
            )}
          </section>
          {mode === "REGISTER" && (
            <section className={styles.section}>
              <div className={styles.sectionTitle}>
                <span>03</span>
                <div>
                  <h2>Connection method</h2>
                  <p>
                    Choose how to deliver the connector into your source
                    cluster.
                  </p>
                </div>
              </div>
              <fieldset disabled={locked || busy}>
                <label>
                  Connector delivery <span>*</span>
                  <select
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
                </label>
                {delivery === "AWS_SSM" ? (
                  <div className={styles.grid}>
                    <label>
                      AWS account ID <span>*</span>
                      <input
                        required
                        inputMode="numeric"
                        pattern="[0-9]{12}"
                        maxLength={12}
                        value={account}
                        onChange={(e) => setAccount(e.target.value)}
                        placeholder="12-digit source AWS account ID"
                      />
                    </label>
                    <label>
                      SSM managed instance ID <span>*</span>
                      <input
                        required
                        pattern="(i-[0-9a-f]{8,17}|mi-[A-Za-z0-9-]+)"
                        value={instance}
                        onChange={(e) => setInstance(e.target.value)}
                        placeholder="i-0123456789abcdef0"
                      />
                      <small>
                        Control-plane or administration host with Kubernetes API
                        access.
                      </small>
                    </label>
                    <label className={styles.full}>
                      Cross-account role ARN{" "}
                      <small>
                        Optional for same-account access; required when using a
                        cross-account role.
                      </small>
                      <input
                        pattern="arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+"
                        maxLength={2048}
                        value={role}
                        onChange={(e) => setRole(e.target.value)}
                        placeholder="arn:aws:iam::123456789012:role/NaviganSourceConnector"
                      />
                    </label>
                    <label className={styles.full}>
                      Kubeconfig path on the source host <span>*</span>
                      <input
                        required
                        pattern="/[A-Za-z0-9._/-]+"
                        maxLength={512}
                        value={kubeconfig}
                        onChange={(e) => setKubeconfig(e.target.value)}
                      />
                      <small>
                        Path on the SSM managed host, not on your browser or
                        laptop.
                      </small>
                    </label>
                  </div>
                ) : (
                  <p className={styles.methodNote}>
                    Navigan generates a short-lived enrollment configuration.
                    Your cluster administrator applies the connector using the
                    existing approved Helm chart
                    {delivery === "GITOPS"
                      ? " through your GitOps repository"
                      : ""}
                    . No kubeconfig contents are uploaded.
                  </p>
                )}
              </fieldset>
            </section>
          )}
          <section className={styles.section} aria-label="Connection status">
            <div className={styles.sectionTitle}>
              <span>
                <ShieldCheck size={19} />
              </span>
              <div>
                <h2>Connection status</h2>
                <p>
                  {verifiedAt
                    ? "Connected · recent connector heartbeat verified"
                    : source
                      ? "Registered · awaiting verification"
                      : "Not connected"}
                </p>
              </div>
              {verifiedAt && <CheckCircle2 color="#438000" />}
            </div>
            <div aria-live="polite">
              {notice && <p>{notice}</p>}
              {verifiedAt && (
                <small>Verified {new Date(verifiedAt).toLocaleString()}</small>
              )}
              {commandId && <small>SSM command: {commandId}</small>}
              {draft && <small>Assessment ID: {draft.migrationId}</small>}
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
                </button>{" "}
                <small>
                  Expires {new Date(enrollment.expiresAt).toLocaleString()}.
                  Keep the downloaded credential private.
                </small>
              </p>
            )}
            <div className={styles.actions}>
              {!draft && (
                <button
                  className={styles.primary}
                  type="submit"
                  disabled={
                    busy ||
                    !customer ||
                    !name.trim() ||
                    platform !== "SELF_MANAGED" ||
                    (mode === "EXISTING" && !existingId)
                  }
                >
                  {busy
                    ? "Saving connection…"
                    : mode === "REGISTER"
                      ? "Save assessment & connect source"
                      : "Save assessment & use source"}
                </button>
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
                  {!verifiedAt && (
                    <button
                      type="button"
                      onClick={retryDelivery}
                      disabled={busy || Boolean(checkingUntil)}
                    >
                      {source.deliveryMethod === "AWS_SSM"
                        ? "Retry installation"
                        : "Generate enrollment configuration"}
                    </button>
                  )}
                </>
              )}
            </div>
            {verifiedAt && (
              <p className={styles.next}>
                Source connection is complete. Source Discovery is the next
                screen to be built.
              </p>
            )}
          </section>
        </form>
        <aside
          className={styles.summary}
          aria-label="Source connection summary"
        >
          <div className={styles.summaryIcon}>
            <PlugZap size={25} />
          </div>
          <p className={styles.eyebrow}>STEP 1 OF 6</p>
          <h2>Connect your source</h2>
          <p>
            Establish the connection before discovering applications and
            selecting migration scope.
          </p>
          <dl>
            <dt>Assessment</dt>
            <dd>{name || "Not entered"}</dd>
            <dt>Customer</dt>
            <dd>
              {selectedCustomer?.name || source?.customerName || "Not selected"}
            </dd>
            <dt>Source cluster</dt>
            <dd>{source?.name || clusterName || "Not selected"}</dd>
            <dt>Connection</dt>
            <dd>
              {verifiedAt
                ? "Connected"
                : source
                  ? "Awaiting verification"
                  : "Not connected"}
            </dd>
            <dt>Target</dt>
            <dd>Selected later</dd>
          </dl>
          <div className={styles.assurance}>
            <ShieldCheck size={19} />
            <p>
              Source access is read-only. Discovery starts in the next stage.
            </p>
          </div>
          <p className={styles.small}>
            One connector registration per cluster. A customer account can have
            multiple connected clusters.
          </p>
        </aside>
      </div>
    </main>
  );
}
