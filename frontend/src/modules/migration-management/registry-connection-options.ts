export const registryProviders = [
  ["AWS_ECR", "Amazon ECR (AWS)"],
  ["AZURE_ACR", "Azure Container Registry"],
  ["GOOGLE_AR", "Google Artifact Registry / GCR"],
  ["DOCKER_HUB", "Docker Hub"],
  ["GHCR", "GitHub Container Registry"],
  ["HARBOR", "Harbor"],
  ["OTHER", "Other OCI / Docker registry"],
] as const;

export function detectRegistryProvider(host: string): string {
  if (/^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com$/.test(host))
    return "AWS_ECR";
  if (host.endsWith(".azurecr.io")) return "AZURE_ACR";
  if (
    host.endsWith(".pkg.dev") ||
    host.endsWith(".gcr.io") ||
    host === "gcr.io"
  )
    return "GOOGLE_AR";
  if (host === "docker.io") return "DOCKER_HUB";
  if (host === "ghcr.io") return "GHCR";
  return "OTHER";
}
export function registryMethods(provider: string): [string, string][] {
  if (provider === "AWS_ECR")
    return [
      ["AWS_ROLE", "Create new IAM role"],
      ["AWS_EXISTING_ROLE", "Existing IAM role"],
    ];
  if (provider === "AZURE_ACR")
    return [
      ["TOKEN", "Service principal or ACR repository token"],
      ["BEARER", "Azure registry bearer token"],
      ["PUBLIC", "Public / anonymous"],
    ];
  if (provider === "GOOGLE_AR")
    return [
      ["TOKEN", "Google OAuth access token"],
      ["PUBLIC", "Public / anonymous"],
    ];
  return [
    ["PUBLIC", "Public / anonymous"],
    [
      "TOKEN",
      provider === "GHCR"
        ? "GitHub username and read:packages token"
        : provider === "HARBOR"
          ? "Robot account and pull token"
          : "Registry username and access token",
    ],
    ["BEARER", "Registry bearer token"],
  ];
}
export function registryRoleArn(host: string) {
  const account = /^([0-9]{12})\.dkr\.ecr\./.exec(host)?.[1];
  return account
    ? `arn:aws:iam::${account}:role/navigan-source-discovery/NaviganRegistryReadOnly`
    : "";
}

export function registryPlaceholder(provider: string) {
  return (
    (
      {
        AWS_ECR: "123456789012.dkr.ecr.ap-south-1.amazonaws.com",
        AZURE_ACR: "customer.azurecr.io",
        GOOGLE_AR: "asia-south1-docker.pkg.dev",
        DOCKER_HUB: "docker.io",
        GHCR: "ghcr.io",
        HARBOR: "harbor.example.com",
        OTHER: "registry.example.com",
      } as Record<string, string>
    )[provider] ?? "registry.example.com"
  );
}

export function registryRoleTemplate(
  host: string,
  roleArn: string,
  principal: string,
  externalId: string,
) {
  const match = /^([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com$/.exec(
    host,
  );
  if (
    !match ||
    !roleArn.startsWith(
      `arn:aws:iam::${match[1]}:role/navigan-source-discovery/`,
    ) ||
    !principal ||
    !externalId
  )
    throw new Error(
      "Save a valid registry role connection before downloading setup.",
    );
  return {
    AWSTemplateFormatVersion: "2010-09-09",
    Description: `Read-only Navigan registry discovery role for account ${match[1]}`,
    Resources: {
      RegistryDiscoveryRole: {
        Type: "AWS::IAM::Role",
        Properties: {
          RoleName: roleArn.split("/").at(-1),
          Path: "/navigan-source-discovery/",
          AssumeRolePolicyDocument: {
            Version: "2012-10-17",
            Statement: [
              {
                Effect: "Allow",
                Principal: { AWS: principal },
                Action: "sts:AssumeRole",
                Condition: { StringEquals: { "sts:ExternalId": externalId } },
              },
            ],
          },
          Policies: [
            {
              PolicyName: "NaviganRegistryMetadataReadOnly",
              PolicyDocument: {
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
                    Resource: `arn:aws:ecr:${match[2]}:${match[1]}:repository/*`,
                  },
                ],
              },
            },
          ],
        },
      },
    },
    Outputs: {
      RegistryRoleArn: {
        Value: { "Fn::GetAtt": ["RegistryDiscoveryRole", "Arn"] },
      },
    },
  };
}
