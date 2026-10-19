"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  GitBranch,
  ShieldCheck,
  Plus,
  Trash2,
  LoaderCircle,
} from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import { hasPermission } from "@/shared/auth/permissions";
import { normalizeApiError } from "@/shared/api/client";
import {
  deploymentDiscovery,
  type DeploymentSourcesConfiguration,
} from "./deployment-evidence-service";
import styles from "./deployment-evidence-panel.module.css";

type Credential = {
  key: string;
  mode: string;
  username?: string;
  token?: string;
};
const normalizeRepo = (value: string) =>
  value
    .trim()
    .replace(/^https:\/\/github.com\//, "")
    .replace(/\/$/, "")
    .replace(/\.git$/, "");

export function SourceConnectionsPanel({ sourceId }: { sourceId: string }) {
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
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const configuration = draft ?? settings.data?.configuration;
  const dirty = draft !== null || Object.keys(credentials).length > 0;
  function change(key: string, value: Partial<Credential>) {
    setCredentials((old) => ({
      ...old,
      [key]: {
        ...(old[key] ?? {
          key,
          mode:
            settings.data?.authentication?.[key]?.mode ??
            (key.startsWith("github:")
              ? "PUBLIC"
              : key.includes(".dkr.ecr.")
                ? "AWS_IAM"
                : "PUBLIC"),
        }),
        ...value,
      },
    }));
  }
  function authFields(key: string, github: boolean) {
    const saved = settings.data?.authentication?.[key];
    const value = credentials[key] ?? {
      key,
      mode:
        saved?.mode ??
        (github ? "PUBLIC" : key.includes(".dkr.ecr.") ? "AWS_IAM" : "PUBLIC"),
    };
    return (
      <>
        <label>
          Authentication *{" "}
          <select
            aria-label={`Authentication for ${key}`}
            value={value.mode}
            onChange={(e) =>
              change(key, { mode: e.target.value, token: "", username: "" })
            }
            title="Choose read-only access for source discovery."
          >
            <option value="PUBLIC">Public / anonymous</option>
            {github ? (
              <option value="APP">Existing customer GitHub App</option>
            ) : (
              <option value="AWS_IAM">AWS ECR · Navigan IAM role</option>
            )}
            <option value="TOKEN">
              {github
                ? "Fine-grained GitHub token"
                : "Registry username and access token"}
            </option>
            {!github && <option value="BEARER">Registry bearer token</option>}
          </select>
        </label>
        {!github && value.mode === "TOKEN" && (
          <label>
            Registry username *{" "}
            <input
              autoComplete="off"
              value={value.username ?? ""}
              onChange={(e) => change(key, { username: e.target.value })}
              title="The username associated with a read-only registry token."
            />
          </label>
        )}
        {["TOKEN", "BEARER"].includes(value.mode) && (
          <label>
            {github ? "GitHub token" : "Registry token"}{" "}
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
    const changes = keys.flatMap((key) => {
      // Normalize entered GitHub URLs before matching their write-only credential fields.
      const entered = Object.values(credentials).find(
        (c) =>
          (c.key.startsWith("github:")
            ? "github:" + normalizeRepo(c.key.slice(7))
            : "registry:" + c.key.slice(9).trim().toLowerCase()) === key,
      );
      if (entered) return [{ ...entered, key }];
      if (!settings.data?.authentication?.[key])
        return [
          { key, mode: key.includes(".dkr.ecr.") ? "AWS_IAM" : "PUBLIC" },
        ];
      return [];
    });
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
            ? "Source connections are ready. You can start discovery below."
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
  return (
    <section
      className={styles.panel}
      aria-label="Source connections"
      id="source-connections"
    >
      <div className={styles.heading}>
        <div>
          <h2>
            <ShieldCheck size={20} /> Source connections
          </h2>
          <p>
            Connect application repositories and container registries before
            discovery and assessment.
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
          onSubmit={(e) => {
            e.preventDefault();
            void save(true);
          }}
        >
          <fieldset
            className={styles.connectionFields}
            disabled={!canEdit || !!busy}
          >
            <h3>
              <GitBranch size={16} /> Application source repositories
            </h3>
            <small>
              GitHub.com repositories are supported. Existing customer App
              connections:{" "}
              {settings.data?.githubOrganizations.join(", ") || "none"}.
              Connections are reused by assessments using this customer’s
              registered source cluster.
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
                            repositories: configuration.repositories.map(
                              (item, j) =>
                                j === i
                                  ? { ...item, [field]: e.target.value }
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
            <h3>Container registries</h3>
            <small>
              Add a registry once. Navigan discovers all referenced workload and
              init-container images automatically. Verification checks registry
              API access; image-specific access is checked during analysis.
              Private network endpoints require connector-based access, which is
              not available here yet.
            </small>
            {configuration.registries.map((host, i) => (
              <div className={styles.connectionCard} key={i}>
                <label>
                  Registry hostname *
                  <input
                    required
                    value={host}
                    placeholder="905418045935.dkr.ecr.ap-south-1.amazonaws.com"
                    title="Use a hostname without https:// or an image path. ECR IAM access currently supports the registered source AWS account."
                    onChange={(e) =>
                      setDraft({
                        ...configuration,
                        registries: configuration.registries.map((h, j) =>
                          j === i ? e.target.value : h,
                        ),
                      })
                    }
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
              Continue with inventory-only discovery. Repository and registry
              analysis may be incomplete.
            </label>
            <small>
              Tokens are encrypted in AWS Secrets Manager. Existing tokens are
              never displayed. Navigan uses read-only API operations; choose
              tokens with only read permissions.
            </small>
            <div className={styles.actions}>
              <button type="button" onClick={() => void save(false)}>
                Save connections
              </button>
              <button className={styles.primary} type="submit">
                {busy && <LoaderCircle size={14} className={styles.spin} />}{" "}
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
    </section>
  );
}
