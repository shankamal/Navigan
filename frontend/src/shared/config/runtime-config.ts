"use client";
import { parsePublicConfig, type PublicRuntimeConfig } from "./public-config";

let current: PublicRuntimeConfig = parsePublicConfig({
  oidcAuthority: "",
  oidcClientId: "",
  appUrl: "",
  corporateLogoUrl: "",
  migrationConnectorApiBaseUrl: "",
  migrationConnectorImageRepository: "",
  migrationConnectorImageDigest: "",
  migrationUiPreview: false,
});
let pending: Promise<PublicRuntimeConfig> | undefined;
export let authConfigured = false;

export function runtimeConfig(): PublicRuntimeConfig {
  return current;
}

export function installRuntimeConfig(value: unknown): PublicRuntimeConfig {
  current = parsePublicConfig(value);
  authConfigured = Boolean(current.oidcClientId);
  return current;
}

export function loadRuntimeConfig(): Promise<PublicRuntimeConfig> {
  if (!pending) {
    pending = fetch("/api/runtime-config", {
      cache: "no-store",
      credentials: "same-origin",
      signal: AbortSignal.timeout(10_000),
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error("Runtime configuration is unavailable.");
        return installRuntimeConfig(await response.json());
      })
      .catch((error: unknown) => {
        pending = undefined;
        throw error;
      });
  }
  return pending;
}
