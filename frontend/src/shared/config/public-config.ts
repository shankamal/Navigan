export interface PublicRuntimeConfig {
  oidcAuthority: string;
  oidcClientId: string;
  appUrl: string;
  corporateLogoUrl: string;
  migrationConnectorApiBaseUrl: string;
  migrationConnectorImageRepository: string;
  migrationConnectorImageDigest: string;
  migrationUiPreview: boolean;
}

const fields = [
  "oidcAuthority",
  "oidcClientId",
  "appUrl",
  "corporateLogoUrl",
  "migrationConnectorApiBaseUrl",
  "migrationConnectorImageRepository",
  "migrationConnectorImageDigest",
] as const;

export function parsePublicConfig(value: unknown): PublicRuntimeConfig {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid public runtime configuration.");
  }
  const item = value as Record<string, unknown>;
  if (
    Object.keys(item).some(
      (key) => ![...fields, "migrationUiPreview"].includes(key),
    ) ||
    fields.some(
      (key) => typeof item[key] !== "string" || item[key].length > 2048,
    ) ||
    typeof item.migrationUiPreview !== "boolean"
  ) {
    throw new Error("Invalid public runtime configuration.");
  }
  const config = item as unknown as PublicRuntimeConfig;
  if (
    Boolean(config.oidcAuthority) !== Boolean(config.oidcClientId) ||
    (config.oidcAuthority &&
      !/^https:\/\/cognito-idp\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?\/[a-z0-9-]+_[A-Za-z0-9]+$/.test(
        config.oidcAuthority,
      )) ||
    (config.oidcClientId && !/^[A-Za-z0-9]+$/.test(config.oidcClientId))
  ) {
    throw new Error("Invalid public identity configuration.");
  }
  for (const key of ["appUrl", "migrationConnectorApiBaseUrl"] as const) {
    if (!config[key]) continue;
    const url = new URL(config[key]);
    if (
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      (url.protocol !== "https:" &&
        !(
          url.protocol === "http:" &&
          ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
        )) ||
      (key === "appUrl" && url.pathname !== "/")
    ) {
      throw new Error("Invalid public application URL.");
    }
  }
  if (
    config.corporateLogoUrl &&
    !/^\/(?!\/)/.test(config.corporateLogoUrl) &&
    !/^https:\/\/[^\s@]+$/.test(config.corporateLogoUrl)
  ) {
    throw new Error("Invalid public logo URL.");
  }
  if (
    (config.migrationConnectorImageRepository &&
      !/^[A-Za-z0-9._/-]+$/.test(config.migrationConnectorImageRepository)) ||
    (config.migrationConnectorImageDigest &&
      !/^sha256:[a-f0-9]{64}$/.test(config.migrationConnectorImageDigest))
  ) {
    throw new Error("Invalid public connector image reference.");
  }
  return Object.freeze({ ...config });
}

export function publicConfigFromEnvironment(
  env: Record<string, string | undefined>,
): PublicRuntimeConfig {
  // Exact allowlist, never serialize process.env or a private configuration file.
  // Dynamic lookups also keep legacy NEXT_PUBLIC values out of build-time bundles.
  const read = (name: string) =>
    env[`NAVIGAN_PUBLIC_${name}`] ?? env[`NEXT_PUBLIC_${name}`] ?? "";
  return parsePublicConfig({
    oidcAuthority: read("OIDC_AUTHORITY"),
    oidcClientId: read("OIDC_CLIENT_ID"),
    appUrl: read("APP_URL"),
    corporateLogoUrl: read("CORPORATE_LOGO_URL"),
    migrationConnectorApiBaseUrl: read("MIGRATION_CONNECTOR_API_BASE_URL"),
    migrationConnectorImageRepository: read(
      "MIGRATION_CONNECTOR_IMAGE_REPOSITORY",
    ),
    migrationConnectorImageDigest: read("MIGRATION_CONNECTOR_IMAGE_DIGEST"),
    migrationUiPreview:
      env.NODE_ENV !== "production" && read("MIGRATION_UI_PREVIEW") === "true",
  });
}
