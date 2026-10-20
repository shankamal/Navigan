"use client";

import { useEffect, useState, type ReactNode } from "react";
import { EvidenceDrawer } from "./evidence-drawer";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  GitBranch,
  ShieldCheck,
  Plus,
  Trash2,
  LoaderCircle,
  CheckCircle2,
  Database,
  Server,
  Settings2,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { normalizeApiError } from "@/shared/api/client";
import {
  deploymentDiscovery,
  type DeploymentSourcesConfiguration,
} from "./deployment-evidence-service";
import {
  registryProviders,
  detectRegistryProvider,
  registryMethods,
  registryRoleArn,
  registryPlaceholder,
  registryRoleTemplate,
} from "./registry-connection-options";
import styles from "./deployment-evidence-panel.module.css";

type Credential = {
  key: string;
  mode: string;
  username?: string;
  token?: string;
  roleArn?: string;
  provider?: string;
};
const normalizeRepo = (value: string) =>
  value
    .trim()
    .replace(/^https:\/\/github.com\//, "")
    .replace(/\/$/, "")
    .replace(/\.git$/, "");

export function SourceConnectionsPanel({
  sourceId,
  assessmentComplete = false,
  compact = false,
  openRequest = 0,
  connectorConnected = false,
  connectorName,
}: {
  sourceId: string;
  assessmentComplete?: boolean;
  compact?: boolean;
  openRequest?: number;
  connectorConnected?: boolean;
  connectorName?: string;
}) {
  const { identity } = useAuth();
  const canEdit = hasPermission(identity, "migration.edit");
  const cache = useQueryClient();
  const settings = useQuery({
    queryKey: ["deployment-sources", sourceId],
    queryFn: ({ signal }) => deploymentDiscovery.settings(sourceId, signal),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const [draft, setDraft] = useState<DeploymentSourcesConfiguration | null>(
    null,
  );
  const [credentials, setCredentials] = useState<Record<string, Credential>>(
    {},
  );
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (openRequest) setExpanded(true);
  }, [openRequest]);
  const [connectionTab, setConnectionTab] = useState("overview");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const configuration = draft ?? settings.data?.configuration;
  const dirty = draft !== null || Object.keys(credentials).length > 0;
  function defaults(key: string): Credential {
    const saved = settings.data?.authentication?.[key];
    if (key.startsWith("github:"))
      return { key, mode: saved?.mode ?? "PUBLIC" };
    const host = key.slice(9);
    const provider = saved?.provider || detectRegistryProvider(host);
    const allowed = registryMethods(provider);
    const mode = allowed.some(([mode]) => mode === saved?.mode)
      ? saved!.mode
      : allowed[0][0];
    return {
      key,
      provider,
      mode,
      roleArn: saved?.roleArn || registryRoleArn(host),
      ...(provider === "GOOGLE_AR" ? { username: "oauth2accesstoken" } : {}),
    };
  }
  function change(key: string, value: Partial<Credential>) {
    setCredentials((old) => ({
      ...old,
      [key]: { ...(old[key] ?? defaults(key)), ...value },
    }));
  }
  function providerField(key: string) {
    const value = credentials[key] ?? defaults(key);
    return (
      <label>
        Registry provider *
        <select
          aria-label={`Registry provider for ${key}`}
          value={value.provider}
          onChange={(e) => {
            const provider = e.target.value;
            change(key, {
              provider,
              mode: registryMethods(provider)[0][0],
              token: "",
              username: provider === "GOOGLE_AR" ? "oauth2accesstoken" : "",
            });
          }}
          title="Choose where the source images are stored, independently of the cluster provider."
        >
          {registryProviders.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
    );
  }
  function authFields(key: string, github: boolean) {
    const saved = settings.data?.authentication?.[key];
    const value = credentials[key] ?? defaults(key);
    const host = key.slice(9);
    const ecr = /^([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com$/.exec(
      host,
    );
    const provider =
      registryProviders.find(([id]) => id === value.provider)?.[1] ??
      "Container registry";
    return (
      <>
        {!github && (
          <small>
            <strong>{provider}</strong>
            {ecr && ` · Registry account ${ecr[1]} · Region ${ecr[2]}`} ·
            Independent of the source and target cluster accounts.
          </small>
        )}
        <label>
          Authentication *{" "}
          <select
            aria-label={`Authentication for ${key}`}
            value={value.mode}
            onChange={(e) =>
              change(key, {
                mode: e.target.value,
                ...(github
                  ? {}
                  : {
                      roleArn:
                        e.target.value === "AWS_EXISTING_ROLE"
                          ? (saved?.roleArn ?? "")
                          : registryRoleArn(host),
                    }),
                token: "",
                username:
                  value.provider === "GOOGLE_AR" ? "oauth2accesstoken" : "",
              })
            }
            title="Choose read-only access for source discovery."
          >
            {github ? (
              <>
                <option value="PUBLIC">Public / anonymous</option>
                <option value="APP">Existing customer GitHub App</option>
                <option value="TOKEN">Fine-grained GitHub token</option>
              </>
            ) : (
              registryMethods(value.provider ?? "OTHER").map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))
            )}
          </select>
        </label>
        {!github && ["AWS_ROLE", "AWS_EXISTING_ROLE"].includes(value.mode) && (
          <>
            <label>
              {value.mode === "AWS_EXISTING_ROLE"
                ? "Existing IAM role ARN *"
                : "Registry read-only role ARN *"}
              <input
                required
                value={value.roleArn ?? ""}
                placeholder={`arn:aws:iam::${ecr?.[1] ?? "123456789012"}:role/navigan-source-discovery/NaviganRegistryReadOnly`}
                title={
                  value.mode === "AWS_EXISTING_ROLE"
                    ? "Enter your existing registry-account role ARN. It must trust Navigan with the generated External ID and permit read-only ECR discovery."
                    : "New role setup uses IAM path /navigan-source-discovery/."
                }
                onChange={(e) => change(key, { roleArn: e.target.value })}
              />
            </label>
            <small>
              {value.mode === "AWS_EXISTING_ROLE"
                ? "Save this existing role connection to generate an External ID. Add the trust statement below to the existing role and attach the read-only ECR policy, then verify. Preserve existing trust statements (including EC2 or other services). No new role is created."
                : "Save connections first to generate your External ID. Create the new role using the setup below, then verify access."}
            </small>
            {value.mode === "AWS_EXISTING_ROLE" && (
              <small>
                For a role outside /navigan-source-discovery/, the deployment
                administrator must authorize its exact ARN once using{" "}
                <code>--registry-role-arn YOUR_EXISTING_ROLE_ARN</code> with the
                DEV deployment script. This does not change the role’s own trust
                or permissions.
              </small>
            )}
            {value.mode === "AWS_EXISTING_ROLE" && (
              <small>
                Merge the displayed trust statement into the existing trust
                policy; keep existing EC2, EKS and other service trust
                statements. Attach the displayed ECR permissions as an
                additional policy.
              </small>
            )}
            {saved?.externalId ? (
              <>
                <label>
                  Navigan-generated External ID
                  <input
                    readOnly
                    value={saved.externalId}
                    title="Add this exact value to the registry role trust policy. It is generated and bound to this customer/source registry connection."
                  />
                </label>
                {settings.data?.registryPrincipalArn ? (
                  <details>
                    <summary>Customer role trust and permissions</summary>
                    {value.mode === "AWS_ROLE" && (
                      <button
                        type="button"
                        onClick={() => {
                          const template = registryRoleTemplate(
                            host,
                            saved.roleArn!,
                            settings.data!.registryPrincipalArn!,
                            saved.externalId!,
                          );
                          const url = URL.createObjectURL(
                            new Blob([JSON.stringify(template, null, 2)], {
                              type: "application/json",
                            }),
                          );
                          const link = document.createElement("a");
                          link.href = url;
                          link.download = "navigan-registry-role.json";
                          link.click();
                          setTimeout(() => URL.revokeObjectURL(url), 1000);
                        }}
                      >
                        Download AWS role setup
                      </button>
                    )}
                    {value.mode === "AWS_ROLE" && (
                      <small>
                        Deploy the downloaded CloudFormation template in the
                        registry account ({ecr?.[1]}), then verify access. It
                        creates the chosen role, IAM path, External ID trust and
                        read-only metadata permissions. If the role already
                        exists, update its policies instead of creating it
                        again.
                      </small>
                    )}
                    {value.mode === "AWS_ROLE" && (
                      <p>
                        Create the role with IAM path{" "}
                        <code>/navigan-source-discovery/</code>.
                      </p>
                    )}
                    <label>
                      Trust policy
                      <textarea
                        readOnly
                        rows={12}
                        value={JSON.stringify(
                          {
                            Version: "2012-10-17",
                            Statement: [
                              {
                                Effect: "Allow",
                                Principal: {
                                  AWS: settings.data.registryPrincipalArn,
                                },
                                Action: "sts:AssumeRole",
                                Condition: {
                                  StringEquals: {
                                    "sts:ExternalId": saved.externalId,
                                  },
                                },
                              },
                            ],
                          },
                          null,
                          2,
                        )}
                      />
                    </label>
                    <label>
                      Read-only ECR permission policy
                      <textarea
                        readOnly
                        rows={12}
                        value={JSON.stringify(
                          {
                            Version: "2012-10-17",
                            Statement: [
                              {
                                Effect: "Allow",
                                Action: ["ecr:GetAuthorizationToken"],
                                Resource: "*",
                              },
                              {
                                Effect: "Allow",
                                Action: ["ecr:DescribeImages"],
                                Resource: `arn:aws:ecr:${ecr?.[2]}:${ecr?.[1]}:repository/*`,
                              },
                            ],
                          },
                          null,
                          2,
                        )}
                      />
                    </label>
                  </details>
                ) : (
                  <p>
                    Deploy the latest DEV backend to display Navigan’s trusted
                    IAM principal.
                  </p>
                )}
              </>
            ) : (
              <small>
                External ID will appear after you save this role connection.
              </small>
            )}
          </>
        )}
        {!github && !ecr && (
          <small>
            Use public access, a registry username with a read-only token, or a
            pre-issued bearer token supported by your provider. Cloud federation
            is not configured by this form. Separate token-service hosts require
            a pre-issued bearer token.
          </small>
        )}
        {!github && value.mode === "TOKEN" && (
          <label>
            {value.provider === "AZURE_ACR"
              ? "Application (client) ID or ACR token username *"
              : value.provider === "GOOGLE_AR"
                ? "Google token username"
                : value.provider === "HARBOR"
                  ? "Robot account username *"
                  : "Registry username *"}{" "}
            <input
              autoComplete="off"
              value={value.username ?? ""}
              readOnly={value.provider === "GOOGLE_AR"}
              onChange={(e) => change(key, { username: e.target.value })}
              title="The username associated with a read-only registry token."
            />
          </label>
        )}
        {["TOKEN", "BEARER"].includes(value.mode) && (
          <label>
            {github
              ? "GitHub token"
              : value.provider === "AZURE_ACR"
                ? "Client secret or ACR token password"
                : value.provider === "GOOGLE_AR"
                  ? "Google access token"
                  : "Registry token"}{" "}
            {saved?.secretConfigured
              ? "(saved securely; leave blank to keep)"
              : "*"}
            <input
              type="password"
              autoComplete="new-password"
              value={value.token ?? ""}
              onChange={(e) => change(key, { token: e.target.value })}
              title={
                github
                  ? "Use an expiring fine-grained token restricted to the source repository, with Contents: read-only. Never enter your GitHub password."
                  : "Use a read-only pull token. Credentials are encrypted in Secrets Manager and never returned."
              }
            />
            {github && (
              <small>
                <a
                  href="https://github.com/settings/personal-access-tokens/new"
                  target="_blank"
                  rel="noreferrer"
                >
                  Create a fine-grained token
                </a>{" "}
                with access to this repository and Contents: read-only.
              </small>
            )}
          </label>
        )}
        {!github && saved?.mode === "AWS_IAM" && (
          <p role="status">
            Replace the previous platform IAM connection with a customer-managed
            registry role. Save to generate its External ID.
          </p>
        )}
        {!github && value.provider === "AZURE_ACR" && (
          <small>
            For service-principal access, enter the application client ID and
            client secret. Assign only the registry/repository read permissions
            required for discovery. Native identity federation is not connected
            by this method.
          </small>
        )}
        {!github && value.provider === "GOOGLE_AR" && (
          <small>
            Use a short-lived Google OAuth access token with Artifact Registry
            read access. The username is oauth2accesstoken. Replace the token
            when it expires; automatic federation is not available yet.
          </small>
        )}
        <small role="status">
          {dirty
            ? "Changes need saving and verification."
            : saved?.status === "CONNECTED"
              ? `Connected · ${saved.message ?? "Access verified"}`
              : (saved?.message ?? "Not verified")}
        </small>
      </>
    );
  }
  async function save(verify: boolean) {
    if (!configuration || !settings.data) return;
    setError("");
    setNotice("");
    const cleaned = {
      ...configuration,
      repositories: configuration.repositories.map((r) => ({
        ...r,
        repository: normalizeRepo(r.repository),
      })),
      registries: configuration.registries.map((h) => h.trim().toLowerCase()),
    };
    if (
      cleaned.repositories.some(
        (r) =>
          !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(r.repository) ||
          !r.revision.trim() ||
          r.directory.startsWith("/") ||
          r.directory.split("/").some((p) => [".", ".."].includes(p)),
      ) ||
      cleaned.registries.some(
        (h) => !/^[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?$/.test(h),
      ) ||
      new Set(cleaned.registries).size !== cleaned.registries.length
    ) {
      setError(
        "Enter a GitHub repository URL or owner/repository, revision, relative directory, and unique registry hostnames without paths.",
      );
      return;
    }
    const keys = [
      ...cleaned.repositories.map((r) => "github:" + r.repository),
      ...cleaned.registries.map((h) => "registry:" + h),
    ];
    const changes: Credential[] = keys.flatMap((key) => {
      // Normalize entered GitHub URLs before matching their write-only credential fields.
      const entered = Object.values(credentials).find(
        (c) =>
          (c.key.startsWith("github:")
            ? "github:" + normalizeRepo(c.key.slice(7))
            : "registry:" + c.key.slice(9).trim().toLowerCase()) === key,
      );
      if (entered) return [{ ...entered, key }];
      if (
        !settings.data?.authentication?.[key] ||
        settings.data.authentication[key].mode === "AWS_IAM"
      )
        return [defaults(key)];
      return [];
    });
    if (
      changes.some(
        (c) =>
          ["AWS_ROLE", "AWS_EXISTING_ROLE"].includes(c.mode) &&
          !/^arn:aws:iam::[0-9]{12}:role\/[A-Za-z0-9+=,.@_-]+(?:\/[A-Za-z0-9+=,.@_-]+)*$/.test(
            c.roleArn ?? "",
          ),
      )
    ) {
      setError(
        "Enter a valid registry-account role ARN, then save to generate an External ID.",
      );
      return;
    }
    if (
      changes.some(
        (c) =>
          ["TOKEN", "BEARER"].includes(c.mode) &&
          !c.token &&
          !settings.data?.authentication?.[c.key]?.secretConfigured,
      )
    ) {
      setError(
        "Enter the mandatory read-only token for each new private connection.",
      );
      return;
    }
    setBusy(verify ? "verify" : "save");
    try {
      const result = await deploymentDiscovery.saveSettings(
        sourceId,
        settings.data.version,
        cleaned,
        changes,
        verify,
      );
      cache.setQueryData(["deployment-sources", sourceId], result);
      setDraft(null);
      setCredentials({}); // Remove plaintext credentials immediately after successful submission.
      setNotice(
        verify
          ? result.readyForDiscovery
            ? assessmentComplete
              ? "Source connections verified. Use Run discovery again for fresh cluster evidence, or Analyze deployment sources below for repository and registry analysis."
              : "Source connections are ready. You can start discovery below."
            : "Settings saved. Review the connection status and correct any access failures."
          : "Settings saved securely. Verify access before starting discovery.",
      );
      await cache.invalidateQueries({ queryKey: ["deployment-evidence"] });
    } catch (e) {
      setCredentials({}); // Do not retain tokens after a failed request.
      setError(
        normalizeApiError(e).message ||
          "Connection setup failed. Retry after checking access.",
      );
      await settings.refetch();
    } finally {
      setBusy("");
    }
  }
  const showConfiguration = !compact || expanded;
  const auth = settings.data?.authentication ?? {};
  const repositories = configuration?.repositories ?? [];
  const registries = configuration?.registries ?? [];
  const githubVerified =
    repositories.length > 0 &&
    repositories.every(
      (repo) => auth[`github:${repo.repository}`]?.status === "CONNECTED",
    );
  const registriesVerified =
    registries.length > 0 &&
    registries.every(
      (host) => auth[`registry:${host}`]?.status === "CONNECTED",
    );
  return (
    <section
      className={`${styles.panel} ${compact ? styles.compactConnections : ""}`}
      aria-label="Source connections"
      id="source-connections"
    >
      {compact && (
        <div className={styles.connectionStrip}>
          <div>
            <Server size={22} />
            <span>
              <strong>Source connector</strong>
              <small>{connectorName || "Registered source cluster"}</small>
            </span>
            <span
              className={
                connectorConnected ? styles.successText : styles.mutedText
              }
            >
              {connectorConnected && <CheckCircle2 size={14} />}{" "}
              {connectorConnected ? "Connected" : "Check status"}
            </span>
          </div>
          <div>
            <GitBranch size={22} />
            <span>
              <strong>GitHub</strong>
              <small>
                {repositories.length === 1
                  ? repositories[0].repository
                  : repositories.length
                    ? `${repositories.length} repositories`
                    : "Not configured"}
              </small>
            </span>
            <span
              className={githubVerified ? styles.successText : styles.mutedText}
            >
              {githubVerified
                ? "Verified"
                : configuration?.inventoryOnly
                  ? "Inventory only"
                  : "Review access"}
            </span>
          </div>
          <div>
            <Database size={22} />
            <span>
              <strong>Source registry</strong>
              <small title={registries.join(", ")}>
                {registries.length === 1
                  ? registries[0]
                  : registries.length
                    ? `${registries.length} registries`
                    : "Not configured"}
              </small>
            </span>
            <span
              className={
                registriesVerified ? styles.successText : styles.mutedText
              }
            >
              {registriesVerified
                ? "Verified"
                : configuration?.inventoryOnly
                  ? "Inventory only"
                  : "Review access"}
            </span>
          </div>
          <button
            aria-expanded={showConfiguration}
            aria-controls="source-connection-configuration"
            onClick={() => setExpanded((v) => !v)}
            disabled={Boolean(busy) || !settings.data}
          >
            <Settings2 size={15} />
            {expanded ? "Hide connections" : "Manage connections"}
          </button>
        </div>
      )}
      {showConfiguration && (
        <ConnectionSurface
          wide={connectionTab !== "overview"}
          modal={compact && expanded}
          onClose={() => {
            if (busy || dirty) {
              setError(
                "Save or discard your changes before closing connections.",
              );
              return;
            }
            setExpanded(false);
          }}
        >
          {compact && expanded && (
            <>
              <nav className={styles.tabs} aria-label="Connection sections">
                {[
                  ["overview", "Overview"],
                  ["repository", "Repository"],
                  ["registries", "Registries"],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    aria-pressed={connectionTab === key}
                    onClick={() => setConnectionTab(key)}
                  >
                    {label}
                  </button>
                ))}
              </nav>
              {connectionTab === "overview" && (
                <div className={styles.connectionOverview}>
                  {[
                    [
                      "Source cluster",
                      connectorName || "Registered source",
                      connectorConnected ? "Connected" : "Check status",
                      "cluster",
                    ],
                    [
                      "GitHub",
                      repositories.map((r) => r.repository).join(", ") ||
                        "Not configured",
                      githubVerified ? "Verified" : "Review access",
                      "repository",
                    ],
                    [
                      "Container registries",
                      registries.join(", ") || "Not configured",
                      registriesVerified ? "Verified" : "Review access",
                      "registries",
                    ],
                  ].map(([name, value, status, section]) => (
                    <div key={name}>
                      <strong>
                        {name === "GitHub" ? (
                          <GitBranch size={21} />
                        ) : name === "Source cluster" ? (
                          <Server size={21} />
                        ) : (
                          <Database size={21} />
                        )}{" "}
                        {name}
                      </strong>
                      <span>{value}</span>
                      <small>{status} · Read-only access</small>
                      {section !== "cluster" ? (
                        <button onClick={() => setConnectionTab(section)}>
                          Manage{" "}
                          {name === "GitHub" ? "repository" : "registries"}
                        </button>
                      ) : (
                        <small>
                          Cluster registration is managed in Source connection.
                        </small>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
          <div hidden={compact && expanded && connectionTab === "overview"}>
            <div className={styles.heading}>
              <div>
                <h2>
                  <ShieldCheck size={20} /> Source connections
                </h2>
                <p>
                  Connect application repositories and container registries
                  before discovery and assessment.
                </p>
              </div>
              <strong>
                {dirty
                  ? "Unsaved changes"
                  : settings.data?.readyForDiscovery
                    ? configuration?.inventoryOnly
                      ? "Inventory only"
                      : "Ready for discovery"
                    : "Setup required"}
              </strong>
            </div>
            {settings.isPending && (
              <p role="status">Loading source connection settings…</p>
            )}
            {settings.isError && (
              <p role="alert">
                Could not load source connections.{" "}
                {normalizeApiError(settings.error).message}
                <button onClick={() => void settings.refetch()}>
                  Retry source settings
                </button>
              </p>
            )}
            {!canEdit && (
              <p role="status">
                Your role can view connections. The migration.edit permission is
                required to change them.
              </p>
            )}
            {configuration && (
              <form
                noValidate
                onSubmit={(e) => {
                  e.preventDefault();
                  void save(true);
                }}
              >
                <fieldset
                  className={styles.connectionFields}
                  disabled={!canEdit || !!busy}
                >
                  <div
                    hidden={
                      compact && expanded && connectionTab !== "repository"
                    }
                  >
                    <h3>
                      <GitBranch size={16} /> Application source repositories
                    </h3>
                    <small>
                      GitHub.com repositories are supported. Existing customer
                      App connections:{" "}
                      {settings.data?.githubOrganizations.join(", ") || "none"}.
                      Connections are reused by assessments using this
                      customer’s registered source cluster.
                    </small>
                    {configuration.repositories.map((r, i) => (
                      <div className={styles.connectionCard} key={i}>
                        <div className={styles.connectionGrid}>
                          {(
                            [
                              [
                                "repository",
                                "Repository URL or owner/repository *",
                                "https://github.com/arajendr/RetailFlow",
                              ],
                              ["revision", "Branch, tag or commit *", "main"],
                              [
                                "directory",
                                "Deployment directory",
                                "deploy/production",
                              ],
                            ] as const
                          ).map(([field, label, placeholder]) => (
                            <label key={field}>
                              {label}
                              <input
                                value={r[field]}
                                placeholder={placeholder}
                                required={field !== "directory"}
                                title={
                                  field === "directory"
                                    ? "Optional relative path containing Helm, Kustomize, manifests or deployment scripts."
                                    : "The repository and revision Navigan will inspect with read-only requests."
                                }
                                onChange={(e) =>
                                  setDraft({
                                    ...configuration,
                                    repositories:
                                      configuration.repositories.map(
                                        (item, j) =>
                                          j === i
                                            ? {
                                                ...item,
                                                [field]: e.target.value,
                                              }
                                            : item,
                                      ),
                                  })
                                }
                              />
                            </label>
                          ))}
                        </div>
                        {authFields("github:" + r.repository, true)}
                        <button
                          type="button"
                          aria-label={`Remove repository ${i + 1}`}
                          onClick={() => {
                            setDraft({
                              ...configuration,
                              repositories: configuration.repositories.filter(
                                (_, j) => i !== j,
                              ),
                            });
                            setCredentials({});
                          }}
                        >
                          <Trash2 size={14} /> Remove repository
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      disabled={configuration.repositories.length >= 3}
                      onClick={() =>
                        setDraft({
                          ...configuration,
                          repositories: [
                            ...configuration.repositories,
                            { repository: "", revision: "main", directory: "" },
                          ],
                        })
                      }
                    >
                      <Plus size={14} /> Add repository
                    </button>
                  </div>
                  <div
                    hidden={
                      compact && expanded && connectionTab !== "registries"
                    }
                  >
                    <h3>Container registries</h3>
                    <small>
                      Add a registry once. Navigan discovers all referenced
                      workload and init-container images automatically.
                      Verification checks registry API access; image-specific
                      access is checked during analysis. Private network
                      endpoints require connector-based access, which is not
                      available here yet.
                    </small>
                    {configuration.registries.map((host, i) => (
                      <div className={styles.connectionCard} key={i}>
                        {providerField("registry:" + host)}
                        <label>
                          Registry hostname *
                          <input
                            required
                            value={host}
                            placeholder={registryPlaceholder(
                              (
                                credentials["registry:" + host] ??
                                defaults("registry:" + host)
                              ).provider ?? "OTHER",
                            )}
                            maxLength={253}
                            title="Use a hostname without https:// or an image path. Use the customer IAM role option for a separately authorized AWS account."
                            onChange={(e) => {
                              const nextHost = e.target.value;
                              setDraft({
                                ...configuration,
                                registries: configuration.registries.map(
                                  (h, j) => (j === i ? nextHost : h),
                                ),
                              });
                              setCredentials((old) => {
                                const previousKey = "registry:" + host;
                                const nextKey = "registry:" + nextHost;
                                const detected = detectRegistryProvider(
                                  nextHost.trim().toLowerCase(),
                                );
                                const provider =
                                  detected !== "OTHER"
                                    ? detected
                                    : (old[previousKey]?.provider ?? "OTHER");
                                const next = { ...old };
                                delete next[previousKey];
                                next[nextKey] = {
                                  key: nextKey,
                                  provider,
                                  mode: registryMethods(provider)[0][0],
                                  roleArn: registryRoleArn(nextHost),
                                  username:
                                    provider === "GOOGLE_AR"
                                      ? "oauth2accesstoken"
                                      : "",
                                  token: "",
                                };
                                return next;
                              });
                            }}
                          />
                        </label>
                        {authFields("registry:" + host, false)}
                        <button
                          type="button"
                          aria-label={`Remove registry ${i + 1}`}
                          onClick={() => {
                            setDraft({
                              ...configuration,
                              registries: configuration.registries.filter(
                                (_, j) => j !== i,
                              ),
                            });
                            setCredentials({});
                          }}
                        >
                          <Trash2 size={14} /> Remove registry
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      disabled={configuration.registries.length >= 10}
                      onClick={() =>
                        setDraft({
                          ...configuration,
                          registries: [...configuration.registries, ""],
                        })
                      }
                    >
                      <Plus size={14} /> Add registry
                    </button>
                  </div>
                  <label className={styles.inventoryChoice}>
                    <input
                      type="checkbox"
                      checked={configuration.inventoryOnly ?? false}
                      onChange={(e) =>
                        setDraft({
                          ...configuration,
                          inventoryOnly: e.target.checked,
                        })
                      }
                    />{" "}
                    Continue with inventory-only discovery. Repository and
                    registry analysis may be incomplete.
                  </label>
                  <small>
                    Tokens are encrypted in AWS Secrets Manager. Existing tokens
                    are never displayed. Navigan uses read-only API operations;
                    choose tokens with only read permissions.
                  </small>
                  <div className={styles.actions}>
                    <button type="button" onClick={() => void save(false)}>
                      Save connections
                    </button>
                    <button className={styles.primary} type="submit">
                      {busy && (
                        <LoaderCircle size={14} className={styles.spin} />
                      )}{" "}
                      {busy === "verify"
                        ? "Verifying access…"
                        : "Save and verify access"}
                    </button>
                    {dirty && (
                      <button
                        type="button"
                        onClick={() => {
                          setDraft(null);
                          setCredentials({});
                        }}
                      >
                        Discard changes
                      </button>
                    )}
                  </div>
                </fieldset>
              </form>
            )}
            {error && (
              <p role="alert" className={styles.error}>
                {error}
              </p>
            )}
            {notice && (
              <p role="status" className={styles.note}>
                {notice}
              </p>
            )}
          </div>
        </ConnectionSurface>
      )}
    </section>
  );
}

function ConnectionSurface({
  modal,
  wide,
  onClose,
  children,
}: {
  modal: boolean;
  wide: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  return modal ? (
    <EvidenceDrawer
      title="Source connections"
      subtitle="Manage read-only repository and registry access"
      variant="connections"
      wide={wide}
      closeLabel="Close source connections"
      onClose={onClose}
    >
      <div id="source-connection-configuration">{children}</div>
    </EvidenceDrawer>
  ) : (
    <div id="source-connection-configuration">{children}</div>
  );
}
