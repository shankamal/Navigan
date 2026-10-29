import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, it, expect, vi } from "vitest";
import { EnvironmentEditor } from "@/modules/environment-management/components/environment-form";
import { apiClient } from "@/shared/api/client";
import { environments } from "@/modules/environment-management/services/environments";
import { engineer, customer } from "./fixtures";
import type { AwsDiscovery } from "@/modules/environment-management/model/types";
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: engineer }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/modules/environment-management/services/environments", () => ({
  environments: {
    metadata: vi.fn(),
    schema: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    discoverAws: vi.fn(),
    action: vi.fn(),
  },
}));
const discovery = {
  cloudProvider: "AWS",
  kubernetesDistribution: "EKS",
  account: { accountId: "123456789012", principalArn: "arn:test" },
  roleArn: "arn:aws:iam::123456789012:role/NaviganDiscoveryRole",
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
        {
          aliasName: "alias/eks",
          keyArn: "arn:aws:kms:key/eks",
          eligibility: "READY",
        },
      ],
      eksClusters: [],
      ecrRepositories: [],
      serviceQuotas: [],
      ebsEncryptionByDefault: true,
    },
  ],
  iamRoles: [
    {
      roleName: "NaviganEKSClusterRole",
      roleArn: "arn:cluster",
      roleType: "CLUSTER",
      eligibility: "READY",
    },
    {
      roleName: "NaviganEKSNodeRole",
      roleArn: "arn:node",
      roleType: "NODE",
      eligibility: "READY",
    },
  ],
  provisioningRoles: [
    { roleName: "NaviganProvisioningRole", roleArn: "arn:provisioning" },
  ],
  provisioningSecrets: [
    { name: "navigan/provisioning/CUS-test", arn: "arn:secret" },
  ],
  counts: {},
  fetchedAt: "2026-09-09T12:00:00Z",
} as AwsDiscovery;

const mount = () =>
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
          },
        })
      }
    >
      <EnvironmentEditor />
    </QueryClientProvider>,
  );
async function identityFields() {
  await screen.findByRole("option", { name: /Example Corporation/ });
  fireEvent.change(screen.getByLabelText("Customer *"), {
    target: { value: customer.customerId },
  });
  fireEvent.change(screen.getByLabelText("Environment name *"), {
    target: { value: "studio-dev" },
  });
  fireEvent.change(screen.getByLabelText("Environment type *"), {
    target: { value: "DEV" },
  });
  fireEvent.change(screen.getByLabelText(/^Cost center/), {
    target: { value: "CC-123" },
  });
}
async function connect() {
  await identityFields();
  fireEvent.change(screen.getByLabelText(/^AWS account ID/), {
    target: { value: "123456789012" },
  });
  fireEvent.change(screen.getByLabelText(/^Discovery role ARN/), {
    target: { value: discovery.roleArn },
  });
  fireEvent.change(screen.getByLabelText(/^External ID/), {
    target: { value: "fixture-external-id" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Fetch AWS inventory" }));
  await screen.findByText(/AWS account 123456789012 connected/);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(apiClient, "get").mockResolvedValue({
    data: {
      items: [{ ...customer, status: "ACTIVE" }],
      pagination: { page: 0, pageSize: 50, totalElements: 1, totalPages: 1 },
    },
  });
  vi.mocked(environments.metadata).mockResolvedValue({
    environmentTypes: ["DEV", "UAT"],
    distributions: [],
  });
  vi.mocked(environments.schema).mockResolvedValue({ type: "object" });
  vi.mocked(environments.discoverAws).mockResolvedValue(discovery);
  vi.mocked(environments.create).mockResolvedValue({
    environmentId: "ENV-studio",
    version: 1,
  } as never);
});
describe("Environment setup studio preserves workflow", () => {
  it("retains the shared title and saves an incomplete draft without calling discovery or submit", async () => {
    mount();
    expect(
      screen.getByRole("heading", { name: "Create environment" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to environments" }),
    ).toHaveAttribute("href", "/environments");
    await identityFields();
    expect(
      screen.getByRole("button", { name: "Review and Submit" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save as Draft" }));
    await waitFor(() => expect(environments.create).toHaveBeenCalledTimes(1));
    expect(environments.create).toHaveBeenCalledWith(
      expect.objectContaining({
        customerId: customer.customerId,
        environmentName: "studio-dev",
        configuration: { tags: { CostCenter: "CC-123" } },
      }),
      expect.objectContaining({ key: expect.any(String) }),
    );
    expect(environments.discoverAws).not.toHaveBeenCalled();
    expect(environments.action).not.toHaveBeenCalled();
  });
  it("opens discovered infrastructure, keeps selections on collapse, and only enables review after applying", async () => {
    const { container } = mount();
    await connect();
    expect(environments.discoverAws).toHaveBeenCalledWith(
      expect.objectContaining({
        customerId: customer.customerId,
        accountId: "123456789012",
        regions: ["ap-south-1"],
      }),
    );
    const panel = container.querySelector<HTMLDetailsElement>(
      ".environment-studio-infrastructure",
    )!;
    expect(panel.open).toBe(true);
    expect(
      screen.getByRole("button", { name: "Review and Submit" }),
    ).toBeDisabled();
    const vpc = screen.getByLabelText("VPC *");
    fireEvent.click(within(panel).getByText("Infrastructure baseline"));
    fireEvent.click(within(panel).getByText("Infrastructure baseline"));
    expect(vpc).toHaveValue("vpc-ready");
    fireEvent.click(
      screen.getByRole("button", { name: "Apply selected baseline" }),
    );
    expect(
      screen.getByRole("button", { name: "Review and Submit" }),
    ).toBeEnabled();
    expect(environments.create).not.toHaveBeenCalled();
    expect(environments.action).not.toHaveBeenCalled();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: "Review and Submit" }));
    expect(
      screen.getByRole("heading", { name: "Confirm the environment baseline" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Submit for Review" }));
    await waitFor(() =>
      expect(environments.action).toHaveBeenCalledWith(
        "ENV-studio",
        "submit",
        { version: 1, comments: "Submitted from environment review." },
        expect.objectContaining({ version: 1, key: expect.any(String) }),
      ),
    );
  });
  it("shows discovery errors in the connection panel without enabling review", async () => {
    vi.mocked(environments.discoverAws).mockRejectedValue(
      new Error("Read-only discovery unavailable"),
    );
    mount();
    await identityFields();
    fireEvent.change(screen.getByLabelText(/^AWS account ID/), {
      target: { value: "123456789012" },
    });
    fireEvent.change(screen.getByLabelText(/^Discovery role ARN/), {
      target: { value: discovery.roleArn },
    });
    fireEvent.change(screen.getByLabelText(/^External ID/), {
      target: { value: "fixture-external-id" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Fetch AWS inventory" }),
    );
    await screen.findByText("Read-only discovery unavailable");
    expect(
      screen.getByRole("button", { name: "Review and Submit" }),
    ).toBeDisabled();
    expect(environments.create).not.toHaveBeenCalled();
  });
});
