import { Cloud, Server } from "lucide-react";

import styles from "./platform-icon.module.css";

type PlatformIconProps = {
  platform: string;
  size?: "small" | "medium";
};

function normalizedPlatform(platform: string) {
  return platform
    .trim()
    .toUpperCase()
    .replaceAll("-", "_")
    .replaceAll(" ", "_");
}

export function PlatformIcon({ platform, size = "small" }: PlatformIconProps) {
  const normalized = normalizedPlatform(platform);
  const sizeClass = size === "medium" ? styles.medium : styles.small;

  const asset = ["EKS", "AMAZON_EKS"].includes(normalized)
    ? "amazoneks"
    : ["ECS", "AMAZON_ECS"].includes(normalized)
      ? "amazonecs"
      : ["AWS", "AMAZON_WEB_SERVICES"].includes(normalized)
        ? "amazonwebservices"
    : ["OPENSHIFT", "RED_HAT_OPENSHIFT", "ROSA"].includes(normalized)
      ? "redhatopenshift"
      : ["ARGOCD", "ARGO_CD", "GITOPS"].includes(normalized)
        ? "argo"
      : ["AKS", "AZURE", "AZURE_AKS"].includes(normalized)
      ? "microsoftazure"
      : ["GKE", "GCP", "GOOGLE_CLOUD"].includes(normalized)
        ? "googlecloud"
        : ["OKE", "OCI", "ORACLE_CLOUD"].includes(normalized)
          ? "oracle"
          : normalized.includes("SELF_MANAGED") ||
              ["KUBERNETES", "K8S"].includes(normalized)
            ? "kubernetes"
            : null;
  if (asset) {
    return (
      <span
        className={`${styles.logo} ${styles.imageLogo} ${sizeClass}`}
        aria-hidden="true"
      >
        <img src={`/logos/${asset}.svg`} alt="" />
      </span>
    );
  }
  if (normalized.includes("ON_PREM") || normalized.includes("DATACENTER")) {
    return (
      <span
        className={`${styles.logo} ${styles.onPremises} ${sizeClass}`}
        aria-hidden="true"
      >
        <Server />
      </span>
    );
  }

  return (
    <span
      className={`${styles.logo} ${styles.other} ${sizeClass}`}
      aria-hidden="true"
    >
      <Cloud />
    </span>
  );
}
