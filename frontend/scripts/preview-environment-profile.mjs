// Interactive local-only preview. Requests are intercepted; no live API or AWS account is used.
import { chromium } from "playwright";
import { readFile } from "node:fs/promises";

const browser = await chromium.launch({ headless: false });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
await context.addInitScript(() => {
  const claims = {
    sub: "preview-architect",
    username: "preview-architect",
    roles: JSON.stringify(["PLATFORM_ARCHITECT"]),
    customer_ids: "[]",
    platform_scope: "true",
    customer_create: "true",
    exp: Math.floor(Date.now() / 1000) + 3600,
    iat: Math.floor(Date.now() / 1000),
    auth_time: Math.floor(Date.now() / 1000),
    iss: "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_GtWAW9Owz",
  };
  const token = (use) =>
    [
      btoa(JSON.stringify({ alg: "RS256", typ: "JWT" })),
      btoa(
        JSON.stringify({
          ...claims,
          token_use: use,
          aud: "ci-public-client",
          client_id: "ci-public-client",
          name: "Ashok Rajendran",
        }),
      ),
      "synthetic-preview-signature",
    ].join(".");
  const prefix = "CognitoIdentityServiceProvider.ci-public-client";
  sessionStorage.setItem(`${prefix}.LastAuthUser`, "preview-architect");
  sessionStorage.setItem(
    `${prefix}.preview-architect.accessToken`,
    token("access"),
  );
  sessionStorage.setItem(`${prefix}.preview-architect.idToken`, token("id"));
  sessionStorage.setItem(`${prefix}.preview-architect.clockDrift`, "0");
});

const page = await context.newPage();
page.on("pageerror", (error) => console.error("Page error:", error.message));
const pagination = (items) => ({
  items,
  pagination: {
    page: 0,
    pageSize: 50,
    totalElements: items.length,
    totalPages: 1,
  },
});
const vpcId = "vpc-0a12bc34de56f7890";
const accountId = "123456789012";
const region = "ap-south-1";
const discovery = {
  cloudProvider: "AWS",
  kubernetesDistribution: "EKS",
  account: {
    accountId,
    principalArn: `arn:aws:sts::${accountId}:assumed-role/NaviganDiscoveryRole/preview`,
  },
  roleArn: `arn:aws:iam::${accountId}:role/NaviganDiscoveryRole`,
  regions: [
    {
      region,
      availabilityZones: ["a", "b", "c"].map((zone) => ({
        name: `${region}${zone}`,
        state: "available",
      })),
      vpcs: [
        {
          vpcId,
          name: "prod-platform-vpc",
          cidrBlock: "10.40.0.0/16",
          isDefault: false,
        },
      ],
      subnets: ["a", "b", "c"].map((zone, index) => ({
        subnetId: `subnet-0${zone}${String(index + 1).repeat(15)}`,
        name: `prod-private-${zone}`,
        vpcId,
        availabilityZone: `${region}${zone}`,
        cidrBlock: `10.40.${16 * (index + 1)}.0/20`,
        availableIpAddressCount: 4068 + index,
        mapPublicIpOnLaunch: false,
        routeTableId: `rtb-private-${zone}`,
        type: "PRIVATE",
        egressTarget: `nat-${zone}`,
      })),
      securityGroups: [
        {
          securityGroupId: "sg-0a111111111111111",
          name: "eks-cluster-control-plane",
          description: "EKS control plane traffic",
          vpcId,
        },
        {
          securityGroupId: "sg-0b222222222222222",
          name: "eks-managed-nodes",
          description: "Managed node traffic",
          vpcId,
        },
      ],
      vpcEndpoints: ["ecr.api", "ecr.dkr", "sts"].map((service, index) => ({
        vpcEndpointId: `vpce-0${index + 1}`,
        serviceName: `com.amazonaws.${region}.${service}`,
      })),
      natGateways: [
        {
          natGatewayId: "nat-a",
          vpcId,
          subnetId: "subnet-public-a",
          state: "available",
        },
      ],
      kmsKeys: [
        {
          aliasName: "alias/navigan-eks-volumes",
          keyArn: `arn:aws:kms:${region}:${accountId}:key/11111111-2222-3333-4444-555555555555`,
        },
      ],
      eksClusters: [{ name: "existing-shared-services" }],
      ecrRepositories: [
        {
          repositoryName: "platform/base-images",
          repositoryArn: `arn:aws:ecr:${region}:${accountId}:repository/platform/base-images`,
          imageTagMutability: "IMMUTABLE",
        },
      ],
      serviceQuotas: [
        {
          serviceCode: "eks",
          quotaCode: "L-1194D53C",
          quotaName: "Clusters",
          value: 100,
          adjustable: true,
        },
        {
          serviceCode: "ec2",
          quotaCode: "L-1216C47A",
          quotaName: "Running On-Demand Standard instances",
          value: 256,
          adjustable: true,
        },
      ],
      ebsEncryptionByDefault: true,
    },
  ],
  iamRoles: [
    {
      roleName: "NaviganEKSClusterRole",
      roleArn: `arn:aws:iam::${accountId}:role/NaviganEKSClusterRole`,
    },
    {
      roleName: "NaviganEKSNodeRole",
      roleArn: `arn:aws:iam::${accountId}:role/NaviganEKSNodeRole`,
    },
  ],
  counts: {
    vpcs: 1,
    subnets: 3,
    securityGroups: 2,
    vpcEndpoints: 3,
    natGateways: 1,
    kmsKeys: 1,
    eksClusters: 1,
    ecrRepositories: 1,
    serviceQuotas: 2,
    iamRoles: 2,
  },
  fetchedAt: new Date().toISOString(),
};
let createdEnvironment;

await page.route("**/api/platform/**", async (route) => {
  const request = route.request();
  const path = new URL(request.url()).pathname.replace("/api/platform", "");
  let data;
  if (path === "/customers") {
    data = pagination([
      {
        customerId: "CUS-preview",
        name: "Precision Industries",
        status: "ACTIVE",
        version: 8,
        cloudProviders: ["AWS"],
      },
    ]);
  } else if (path === "/environments/metadata") {
    data = {
      environmentTypes: ["DEV", "TEST", "UAT", "PROD", "DR"],
      distributions: [
        {
          cloudProvider: "AWS",
          kubernetesDistribution: "EKS",
          schemaVersions: ["1.0"],
        },
      ],
    };
  } else if (path === "/environments/configuration-schemas/EKS/1.0") {
    data = JSON.parse(
      await readFile(
        "../src/navigan/modules/environment_management/schemas/eks-1.0.json",
        "utf8",
      ),
    );
  } else if (
    path === "/environments/discover/aws" &&
    request.method() === "POST"
  ) {
    data = discovery;
  } else if (path === "/environments" && request.method() === "POST") {
    createdEnvironment = {
      ...request.postDataJSON(),
      environmentId: "ENV-local-preview",
      customerName: "Precision Industries",
      status: "DRAFT",
      version: 1,
      approvedVersion: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      createdBy: "preview-architect",
      workflow: {},
    };
    data = createdEnvironment;
  } else if (path === "/environments/ENV-local-preview") {
    data = createdEnvironment;
  }
  await route.fulfill({
    status: data ? 200 : 404,
    json: data || {
      error: {
        code: "PREVIEW_NOT_FOUND",
        message: "No preview fixture exists for this request.",
        details: {},
        correlationId: "preview",
      },
    },
  });
});

const base = process.env.TEST_BASE_URL || "http://127.0.0.1:3101";
await page.goto(`${base}/environments/new`);
await page.getByLabel(/^Customer/).selectOption("CUS-preview");
await page.getByLabel(/^Environment name/).fill("India Production Platform");
await page.getByLabel(/^Environment type/).selectOption("PROD");
await page.getByLabel(/^AWS account ID/).fill(accountId);
await page
  .getByLabel(/^Discovery role ARN/)
  .fill(`arn:aws:iam::${accountId}:role/NaviganDiscoveryRole`);
await page.getByLabel(/^External ID/).fill("local-preview-external-id");
await page.getByRole("button", { name: "Fetch details", exact: true }).click();
await page
  .getByRole("heading", {
    name: "Review the exact resources clusters may use",
    exact: true,
  })
  .waitFor();

console.log("Interactive Environment Profile preview is ready.");
console.log(
  "No live API or AWS calls are being made. Close the browser to stop.",
);
console.log(
  "You can select resources and click Save draft to review the detail page.",
);
await new Promise((resolve) => browser.on("disconnected", resolve));
