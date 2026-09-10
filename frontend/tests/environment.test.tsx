import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { isAllowedRoute } from "@/shared/api/proxy";
import { activeCustomerParams } from "@/modules/environment-management/components/environment-form";
import {
  ConfigurationFields,
  cleanConfiguration,
} from "@/modules/environment-management/components/configuration-fields";
import {
  defaultAwsBaselineSelection,
  validateAwsBaselineSelection,
} from "@/modules/environment-management/components/aws-discovery-panel";
import { allowedActions } from "@/modules/environment-management/model/policy";
import type {
  ConfigurationSchema,
  AwsDiscovery,
  Environment,
} from "@/modules/environment-management/model/types";
import type { Identity } from "@/shared/auth/claims";
describe("Environment module", () => {
  const discovery = {
    cloudProvider: "AWS",
    kubernetesDistribution: "EKS",
    account: { accountId: "905418045935", principalArn: "arn:test" },
    roleArn: "arn:aws:iam::905418045935:role/NaviganDiscoveryRole",
    regions: [
      {
        region: "ap-south-1",
        availabilityZones: [],
        vpcs: [
          { vpcId: "vpc-one-zone", name: "default", isDefault: true },
          { vpcId: "vpc-ready", name: "platform", isDefault: false },
        ],
        subnets: [
          {
            subnetId: "subnet-a",
            name: "private-a",
            vpcId: "vpc-one-zone",
            availabilityZone: "ap-south-1a",
            availableIpAddressCount: 100,
            mapPublicIpOnLaunch: false,
            routeTableId: "rtb-a",
            type: "PRIVATE",
            egressTarget: "nat-a",
          },
          {
            subnetId: "subnet-b",
            name: "private-b",
            vpcId: "vpc-ready",
            availabilityZone: "ap-south-1a",
            availableIpAddressCount: 90,
            mapPublicIpOnLaunch: false,
            routeTableId: "rtb-b",
            type: "PRIVATE",
            egressTarget: "nat-b",
          },
          {
            subnetId: "subnet-c",
            name: "private-c",
            vpcId: "vpc-ready",
            availabilityZone: "ap-south-1b",
            availableIpAddressCount: 80,
            mapPublicIpOnLaunch: false,
            routeTableId: "rtb-c",
            type: "PRIVATE",
            egressTarget: "nat-b",
          },
        ],
        securityGroups: [
          {
            securityGroupId: "sg-cluster",
            name: "cluster",
            description: "cluster traffic",
            vpcId: "vpc-ready",
          },
          {
            securityGroupId: "sg-node",
            name: "nodes",
            description: "node traffic",
            vpcId: "vpc-ready",
          },
        ],
        vpcEndpoints: [],
        natGateways: [
          {
            natGatewayId: "nat-b",
            vpcId: "vpc-ready",
            subnetId: "subnet-public",
            state: "available",
          },
        ],
        kmsKeys: [
          { aliasName: "alias/eks", keyArn: "arn:aws:kms:key/eks" },
        ],
        eksClusters: [],
        ecrRepositories: [],
        serviceQuotas: [],
        ebsEncryptionByDefault: true,
      },
    ],
    iamRoles: [
      { roleName: "NaviganEKSClusterRole", roleArn: "arn:cluster" },
      { roleName: "NaviganEKSNodeRole", roleArn: "arn:node" },
    ],
    counts: {},
    fetchedAt: "2026-09-09T12:00:00Z",
  } as AwsDiscovery;

  it("requests ACTIVE customers without excluding customers that already have environments", () => {
    expect(activeCustomerParams("bank", 2)).toEqual({
      search: "bank",
      status: "ACTIVE",
      page: 2,
      pageSize: 50,
      sort: "name,asc",
    });
  });

  it("prefers an EKS-ready VPC and private subnets across availability zones", () => {
    const selected = defaultAwsBaselineSelection(discovery);
    expect(selected.vpcId).toBe("vpc-ready");
    expect(selected.subnetIds).toEqual(["subnet-b", "subnet-c"]);
    expect(validateAwsBaselineSelection(discovery, selected, "CC-123").ready).toBe(true);
  });

  it("blocks a baseline that selects private subnets in only one availability zone", () => {
    const selected = defaultAwsBaselineSelection(discovery);
    const readiness = validateAwsBaselineSelection(
      discovery,
      {
        ...selected,
        subnetIds: ["subnet-b"],
      },
      "CC-123",
    );
    expect(readiness.ready).toBe(false);
    expect(readiness.checks.find((item) => item.id === "subnets")?.passed).toBe(
      false,
    );
  });

  it("requires a cost center before an AWS baseline can be applied", () => {
    const selected = defaultAwsBaselineSelection(discovery);
    const readiness = validateAwsBaselineSelection(discovery, selected, "");
    expect(readiness.ready).toBe(false);
    expect(readiness.checks.find((item) => item.id === "tags")?.passed).toBe(
      false,
    );
  });

  it("allows all documented routes with exact methods", () => {
    const contract = JSON.parse(
      readFileSync(
        resolve(process.cwd(), "../docs/environment-openapi.json"),
        "utf8",
      ),
    ) as { paths: Record<string, Record<string, unknown>> };
    let count = 0;
    for (const [path, methods] of Object.entries(contract.paths))
      for (const method of Object.keys(methods)) {
        const parts = path
          .replace("/api/v1/", "")
          .replace("{environmentId}", "ENV-test")
          .replace("{distribution}", "AKS")
          .replace("{schemaVersion}", "1.0")
          .replace("{version}", "2")
          .split("/");
        expect(isAllowedRoute(method.toUpperCase(), parts)).toBe(true);
        count++;
      }
    expect(count).toBe(22);
    expect(isAllowedRoute("DELETE", ["environments", "ENV-test"])).toBe(false);
    expect(
      isAllowedRoute("POST", ["environments", "ENV-test", "versions"]),
    ).toBe(false);
    expect(
      isAllowedRoute("GET", [
        "environments",
        "configuration-schemas",
        "../../etc",
        "1.0",
      ]),
    ).toBe(false);
  });
  it.each(["aks", "gke", "oke", "eks"])(
    "renders provider-specific %s fields from the actual API schema",
    (dist) => {
      const schema = JSON.parse(
        readFileSync(
          resolve(
            process.cwd(),
            `../src/navigan/modules/environment_management/schemas/${dist}-1.0.json`,
          ),
          "utf8",
        ),
      ) as ConfigurationSchema;
      render(
        <ConfigurationFields schema={schema} value={{}} onChange={vi.fn()} />,
      );
      const label = {
        aks: "Tenant ID",
        gke: "Project ID",
        oke: "Tenancy OCID",
        eks: "Account ID",
      }[dist]!;
      expect(screen.getByLabelText(new RegExp(label))).toBeInTheDocument();
    },
  );
  it("preserves unknown fields and boolean false while removing empty draft inputs", () => {
    expect(
      cleanConfiguration({
        extensions: { feature: false },
        location: { region: "" },
        network: { subnets: [] },
      }),
    ).toEqual({ extensions: { feature: false } });
  });
  it("adds approved subnet entries", () => {
    const change = vi.fn();
    render(
      <ConfigurationFields
        schema={{
          type: "array",
          title: "Node subnets",
          items: { type: "string" },
        }}
        value={[]}
        onChange={change}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add node subnets" }));
    expect(change).toHaveBeenCalledWith([""]);
  });
  it("renders the cluster platform defaults and provisioning sections from the actual EKS schema", () => {
    const schema = JSON.parse(
      readFileSync(
        resolve(
          process.cwd(),
          "../src/navigan/modules/environment_management/schemas/eks-1.0.json",
        ),
        "utf8",
      ),
    ) as ConfigurationSchema;
    render(
      <ConfigurationFields schema={schema} value={{}} onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText(/Kubernetes version/)).toBeInTheDocument();
    expect(
      screen.getByLabelText(/Provisioning role ARN/),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(/External ID secret ARN/),
    ).toBeInTheDocument();
  });
  it("renders integer schema fields as numeric inputs and emits numbers, not strings", () => {
    const change = vi.fn();
    render(
      <ConfigurationFields
        schema={{ type: "integer", title: "Minimum size", minimum: 0, maximum: 1000 }}
        value={0}
        onChange={change}
      />,
    );
    const input = screen.getByLabelText(/Minimum size/) as HTMLInputElement;
    expect(input.type).toBe("number");
    fireEvent.change(input, { target: { value: "3" } });
    expect(change).toHaveBeenCalledWith(3);
  });
  it("restricts approval affordances to architects", () => {
    const env = { status: "UNDER_REVIEW" } as Environment;
    expect(
      allowedActions(env, { roles: ["CLOUD_ENGINEER"] } as Identity),
    ).toEqual([]);
    expect(
      allowedActions(env, { roles: ["PLATFORM_ARCHITECT"] } as Identity),
    ).toEqual(["approve", "reject"]);
  });
});
