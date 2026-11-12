import { Cloud, Layers3, Server } from "lucide-react";

const clouds: Record<string, { label: string; logo?: string }> = {
  AWS: { label: "AWS", logo: "amazonwebservices" },
  AZURE: { label: "Azure", logo: "microsoftazure" },
  GCP: { label: "Google Cloud", logo: "googlecloud" },
  OCI: { label: "Oracle Cloud", logo: "oracle" },
  ON_PREMISES: { label: "On-premises" },
};
const platforms: Record<
  string,
  { label: string; logo: string; cloud?: string; kubernetes: boolean }
> = {
  EKS: {
    label: "Amazon EKS",
    logo: "amazoneks",
    cloud: "AWS",
    kubernetes: true,
  },
  ECS: {
    label: "Amazon ECS",
    logo: "amazonecs",
    cloud: "AWS",
    kubernetes: false,
  },
  AKS: { label: "AKS", logo: "kubernetes", cloud: "AZURE", kubernetes: true },
  GKE: { label: "GKE", logo: "kubernetes", cloud: "GCP", kubernetes: true },
  OPENSHIFT: { label: "OpenShift", logo: "redhatopenshift", kubernetes: true },
  KUBERNETES: { label: "Kubernetes", logo: "kubernetes", kubernetes: true },
  K3S: { label: "K3s", logo: "kubernetes", kubernetes: true },
  RKE2: { label: "RKE2", logo: "kubernetes", kubernetes: true },
};

// Identity presentation only. Adding a logo does not enable an upgrade adapter.
export function containerIdentity(platform: string, cloud?: string) {
  const code = platform.toUpperCase();
  const entry = platforms[code];
  const cloudCode = entry?.cloud ?? cloud?.toUpperCase();
  return {
    cloud: (cloudCode && clouds[cloudCode]) || {
      label: cloud || "Not reported",
    },
    platform: entry ?? { label: platform || "Not reported", logo: undefined },
    kubernetes: entry?.kubernetes ?? false,
  };
}

export function PlatformIdentity({
  identity,
  kind,
}: {
  identity: ReturnType<typeof containerIdentity>;
  kind: "cloud" | "platform";
}) {
  const value = identity[kind];
  const Icon =
    kind === "platform"
      ? Layers3
      : value.label === "On-premises"
        ? Server
        : Cloud;
  return (
    <span className={`upgrade-identity upgrade-identity-${kind}`}>
      {value.logo ? (
        <img
          src={`/logos/${value.logo}.svg`}
          width={26}
          height={26}
          alt=""
          aria-hidden="true"
        />
      ) : (
        <Icon size={24} aria-hidden="true" />
      )}
      <span>{value.label}</span>
    </span>
  );
}
