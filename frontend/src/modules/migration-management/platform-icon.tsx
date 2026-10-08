import { Boxes, Cloud, Server } from "lucide-react";

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

  if (["EKS", "AWS", "AMAZON_EKS"].includes(normalized)) {
    return (
      <span
        className={`${styles.logo} ${styles.aws} ${sizeClass}`}
        aria-hidden="true"
      >
        aws
      </span>
    );
  }

  if (["AKS", "AZURE", "AZURE_AKS"].includes(normalized)) {
    return (
      <span
        className={`${styles.logo} ${styles.azure} ${sizeClass}`}
        aria-hidden="true"
      >
        <span />
      </span>
    );
  }

  if (["GKE", "GCP", "GOOGLE_CLOUD"].includes(normalized)) {
    return (
      <span
        className={`${styles.logo} ${styles.google} ${sizeClass}`}
        aria-hidden="true"
      >
        G
      </span>
    );
  }

  if (["OKE", "OCI", "ORACLE_CLOUD"].includes(normalized)) {
    return (
      <span
        className={`${styles.logo} ${styles.oracle} ${sizeClass}`}
        aria-hidden="true"
      >
        <span />
      </span>
    );
  }

  if (normalized.includes("OPENSHIFT")) {
    return (
      <span
        className={`${styles.logo} ${styles.openshift} ${sizeClass}`}
        aria-hidden="true"
      >
        <span />
      </span>
    );
  }

  if (
    normalized.includes("SELF_MANAGED") ||
    normalized === "KUBERNETES" ||
    normalized === "K8S"
  ) {
    return (
      <span
        className={`${styles.logo} ${styles.kubernetes} ${sizeClass}`}
        aria-hidden="true"
      >
        <Boxes />
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
