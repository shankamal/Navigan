export interface SourceConnectionFields {
  name: string;
  customer: string;
  mode: "REGISTER" | "EXISTING";
  registered: boolean;
  sourceId: string;
  clusterName: string;
  platform: string;
  distribution: string;
  location: string;
  provider: string;
  region: string;
  delivery: string;
  account: string;
  instance: string;
  role: string;
  kubeconfig: string;
}
export type ConnectionFieldErrors = Partial<
  Record<keyof SourceConnectionFields | "connection", string>
>;
export function validateSourceConnection(
  fields: SourceConnectionFields,
  action: "save" | "verify" | "continue",
  verifiedAt = "",
  now = Date.now(),
): ConnectionFieldErrors {
  const e: ConnectionFieldErrors = {};
  if (fields.name.trim().length < 8 || fields.name.trim().length > 100)
    e.name = "Assessment name must contain 8–100 characters.";
  if (!fields.customer) e.customer = "Select an active customer.";
  if (fields.registered || fields.mode === "EXISTING") {
    if (!fields.sourceId) e.sourceId = "Select a source cluster.";
  } else {
    if (!/^[A-Za-z0-9][A-Za-z0-9._ -]{2,99}$/.test(fields.clusterName.trim()))
      e.clusterName =
        "Enter a source cluster name of 3–100 characters using letters, numbers, spaces, dots, underscores or hyphens.";
    if (fields.platform !== "SELF_MANAGED")
      e.platform =
        "Choose Self-managed Kubernetes for the current migration path.";
    if (!fields.distribution)
      e.distribution = "Select a Kubernetes distribution.";
    if (!["CLOUD", "ON_PREMISES", "OTHER"].includes(fields.location))
      e.location = "Select a cluster location.";
    if (fields.location === "CLOUD" && fields.provider !== "AWS")
      e.provider = "Select AWS for the current cloud source path.";
    if (!/^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$/.test(fields.region.trim()))
      e.region = "Enter a valid region or site location (up to 64 characters).";
    if (!["AWS_SSM", "MANUAL_HELM", "GITOPS"].includes(fields.delivery))
      e.delivery = "Select a connector delivery method.";
    if (fields.delivery === "AWS_SSM") {
      if (fields.location !== "CLOUD" || fields.provider !== "AWS")
        e.delivery = "AWS Systems Manager requires an AWS cloud location.";
      if (!/^[0-9]{12}$/.test(fields.account.trim()))
        e.account = "AWS account ID must contain exactly 12 digits.";
      if (!/^[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+$/.test(fields.region.trim()))
        e.region = "Enter a valid AWS region, for example ap-south-1.";
      if (
        !/^(?:i-[0-9a-f]{8,17}|mi-[A-Za-z0-9-]+)$/.test(fields.instance.trim())
      )
        e.instance =
          "Enter a valid SSM managed instance ID, for example i-0123456789abcdef0.";
      if (
        !/^\/[A-Za-z0-9._/-]+$/.test(fields.kubeconfig.trim()) ||
        fields.kubeconfig.length > 512
      )
        e.kubeconfig =
          "Enter an absolute kubeconfig path on the source host, for example /etc/kubernetes/admin.conf.";
      if (
        fields.role.trim() &&
        !/^arn:(?:aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role\/[A-Za-z0-9+=,.@_/-]+$/.test(
          fields.role.trim(),
        )
      )
        e.role =
          "Enter a valid IAM role ARN or leave the optional field empty.";
    }
  }
  if (action !== "save" && (!fields.registered || !fields.sourceId))
    e.sourceId =
      "Save the assessment and register or select its source cluster first.";
  if (action === "continue") {
    const age = now - Date.parse(verifiedAt);
    if (!verifiedAt || !Number.isFinite(age) || age < 0 || age >= 120000)
      e.connection =
        "Verify the source connection again before continuing to discovery.";
  }
  return e;
}
