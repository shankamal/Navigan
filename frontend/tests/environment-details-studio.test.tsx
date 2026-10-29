import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EnvironmentDetails } from "@/modules/environment-management/components/environment-details";
import { environments } from "@/modules/environment-management/services/environments";
import type {
  Environment,
  HistoryKind,
} from "@/modules/environment-management/model/types";
import { architect, engineer } from "./fixtures";

let identity = engineer;
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity }),
}));
vi.mock("@/modules/environment-management/services/environments", () => ({
  environments: {
    get: vi.fn(),
    records: vi.fn(),
    version: vi.fn(),
    action: vi.fn(),
  },
}));
const subnet = {
  subnetId: "subnet-a",
  name: "private-a",
  availabilityZone: "ap-south-1a",
  cidrBlock: "172.31.48.0/20",
  type: "PRIVATE",
  availableIpAddressCount: 90,
  routeTableId: "rtb-a",
};
const env: Environment = {
  environmentId: "env-1",
  customerId: "customer-1",
  customerName: "Example customer",
  environmentName: "Existing EKS baseline",
  description: "Reusable cloud infrastructure baseline",
  environmentType: "DEV",
  cloudProvider: "AWS",
  kubernetesDistribution: "EKS",
  status: "ACTIVE",
  version: 9,
  approvedVersion: 8,
  approvedStatus: "ACTIVE",
  createdAt: "2026-09-14T03:43:00Z",
  updatedAt: "2026-09-14T05:15:00Z",
  createdBy: "engineer-1",
  configurationSchemaVersion: "1.0",
  workflow: { activated: { by: "architect-1", at: "2026-09-14T05:15:00Z" } },
  configuration: {
    account: { accountId: "123456789012" },
    location: { region: "ap-south-1" },
    network: {
      vpc: { vpcId: "vpc-1" },
      nodeSubnets: [subnet],
      clusterSubnets: [subnet],
    },
    iam: { nodeRole: { roleArn: "arn:aws:iam::123456789012:role/NodeRole" } },
    security: { nodeSecurityGroups: [{ securityGroupId: "sg-node" }] },
    encryption: {
      nodeVolumeKmsKey: {
        keyArn: "arn:aws:kms:ap-south-1:123456789012:key/example",
      },
    },
    tags: { Owner: "engineer@example.com", CostCenter: "CC-1" },
    extensions: {
      discovery: {
        fetchedAt: "2026-09-14T05:13:00Z",
        selectedNatGatewayIds: ["nat-1"],
      },
      provisioningContract: {
        instanceTypes: ["m7i.large", "m7i.xlarge"],
        discoveredQuotaLimits: [{ quotaCode: "L-123", value: 5 }],
      },
    },
    customExtension: { description: "Keep unknown fields accessible" },
  },
};
const page = { page: 0, pageSize: 10, totalElements: 11, totalPages: 2 };
const records: Record<
  HistoryKind,
  Awaited<ReturnType<typeof environments.records>>["items"]
> = {
  "status-history": [
    {
      environmentId: "env-1",
      previousStatus: "APPROVED",
      newStatus: "ACTIVE",
      changedAt: "2026-09-14T05:15:00Z",
      changedBy: "architect-1",
      reason: "Activate baseline",
    },
  ],
  reviews: [
    {
      environmentId: "env-1",
      reviewStatus: "APPROVED",
      reviewerId: "architect-1",
      reviewedAt: "2026-09-14T05:15:00Z",
      environmentVersion: 8,
      comments: "Networking reviewed",
    },
  ],
  versions: [
    {
      environmentId: "env-1",
      version: 9,
      createdAt: "2026-09-14T05:15:00Z",
      createdBy: "engineer-1",
      changeReason: "Saved revision",
    },
    {
      environmentId: "env-1",
      version: 8,
      createdAt: "2026-09-14T05:14:00Z",
      createdBy: "engineer-1",
    },
  ],
  "audit-log": [
    {
      environmentId: "env-1",
      action: "UPDATE",
      performedAt: "2026-09-14T05:14:00Z",
      performedBy: "engineer-1",
      oldValue: { tags: { CostCenter: "CC-OLD" } },
      newValue: { tags: { CostCenter: "CC-1" } },
    },
  ],
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <EnvironmentDetails id="env-1" />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  identity = engineer;
  vi.mocked(environments.get).mockResolvedValue(structuredClone(env));
  vi.mocked(environments.records).mockImplementation(
    async (_id, kind, requestedPage) => ({
      items: records[kind],
      pagination: { ...page, page: requestedPage },
    }),
  );
  vi.mocked(environments.version).mockImplementation(async (_id, version) => ({
    ...env,
    version,
  }));
  vi.mocked(environments.action).mockResolvedValue({
    ...env,
    status: "DRAFT",
    version: 10,
  });
  Element.prototype.scrollIntoView = vi.fn();
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
});
describe("Existing environment explorer", () => {
  it("keeps saved and approved versions distinct and combines duplicate subnet assignments", async () => {
    mount();
    await screen.findByRole("heading", { name: "Existing EKS baseline" });
    const table = screen.getByRole("table");
    expect(within(table).getAllByText("private-a")).toHaveLength(1);
    expect(within(table).getByText("Nodes + cluster")).toBeInTheDocument();
    const context = screen.getByRole("region", { name: "Environment context" });
    expect(context).toHaveTextContent("Saved version9");
    expect(context).toHaveTextContent("Approved baselineVersion 8");
    fireEvent.click(
      screen.getByRole("button", { name: "Close subnet details" }),
    );
    expect(
      screen.queryByRole("complementary", { name: "Subnet details" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "View private-a details" }),
    );
    expect(
      screen.getByRole("complementary", { name: "Subnet details" }),
    ).toHaveTextContent("90");
    expect(environments.records).not.toHaveBeenCalled();
  });
  it("keeps catalogues collapsed, unknown settings accessible and copies exact identifiers", async () => {
    const copy = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: copy },
    });
    mount();
    await screen.findByRole("heading", { name: "Network configuration" });
    fireEvent.click(screen.getByRole("button", { name: "Copy VPC ID" }));
    expect(copy).toHaveBeenCalledWith("vpc-1");
    fireEvent.click(screen.getByRole("button", { name: "Compute & quotas" }));
    expect(
      screen.getByText("m7i.large").closest("details"),
    ).not.toHaveAttribute("open");
    fireEvent.click(screen.getByRole("button", { name: "Other settings" }));
    fireEvent.click(screen.getByText("View custom extension"));
    expect(screen.getByText("Keep unknown fields accessible")).toBeVisible();
  });
  it("retains assignment-specific values when the same subnet ID has different saved metadata", async () => {
    const input = structuredClone(env);
    input.configuration.network = {
      vpc: { vpcId: "vpc-1" },
      nodeSubnets: [subnet],
      clusterSubnets: [{ ...subnet, availableIpAddressCount: 75 }],
    };
    vi.mocked(environments.get).mockResolvedValue(input);
    mount();
    await screen.findByText("Assignment-specific saved details");
    fireEvent.click(screen.getByText("Assignment-specific saved details"));
    expect(screen.getByText("75")).toBeVisible();
  });
  it("loads lifecycle history through the existing paginated endpoint and resets the page on tab change", async () => {
    mount();
    await screen.findByRole("heading", { name: "Network configuration" });
    fireEvent.click(screen.getByRole("button", { name: "Status History" }));
    await screen.findByRole("list", { name: "Status changes" });
    expect(
      within(
        screen.getByRole("complementary", { name: "Selected record details" }),
      ).getByText("Activate baseline"),
    ).toBeInTheDocument();
    expect(environments.records).toHaveBeenCalledWith(
      "env-1",
      "status-history",
      0,
    );
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() =>
      expect(environments.records).toHaveBeenCalledWith(
        "env-1",
        "status-history",
        1,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Reviews" }));
    await screen.findByText("Networking reviewed");
    expect(environments.records).toHaveBeenCalledWith("env-1", "reviews", 0);
    fireEvent.click(screen.getByRole("button", { name: "View version 8" }));
    await screen.findByRole("dialog");
    expect(environments.version).toHaveBeenCalledWith("env-1", 8);
  });
  it("offers historical versions as structured read-only snapshots", async () => {
    mount();
    await screen.findByRole("heading", { name: "Network configuration" });
    fireEvent.click(screen.getByRole("button", { name: "Versions" }));
    await screen.findByText("Current saved configuration");
    expect(
      within(screen.getByRole("table")).getByText("Approved baseline"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "View Version 8 record 2" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "View version 8" }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByRole("heading", { name: "Saved configuration" });
    expect(
      within(dialog).getByText("View complete version record"),
    ).toBeInTheDocument();
    expect(environments.action).not.toHaveBeenCalled();
  });
  it("keeps audit restricted to architects and displays the original before/after snapshots", async () => {
    identity = architect;
    mount();
    await screen.findByRole("heading", { name: "Network configuration" });
    fireEvent.click(screen.getByRole("button", { name: "Audit Log" }));
    await screen.findByRole("heading", { name: "Change snapshots" });
    expect(environments.records).toHaveBeenCalledWith("env-1", "audit-log", 0);
    fireEvent.click(screen.getByText("View raw snapshots"));
    expect(screen.getByText(/"before"/)).toHaveTextContent("CC-OLD");
    expect(screen.getByText(/"before"/)).toHaveTextContent('"after"');
    expect(environments.action).not.toHaveBeenCalled();
  });
  it("does not request or reveal Audit Log for an engineer", async () => {
    mount();
    await screen.findByRole("heading", { name: "Network configuration" });
    expect(
      screen.queryByRole("button", { name: "Audit Log" }),
    ).not.toBeInTheDocument();
    expect(environments.records).not.toHaveBeenCalled();
  });
  it("preserves lifecycle confirmation, expected version and idempotency on a new revision", async () => {
    mount();
    await screen.findByRole("heading", { name: "Network configuration" });
    fireEvent.click(screen.getByRole("button", { name: "Lifecycle actions" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Create new revision" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm create new revision" }),
    );
    await waitFor(() =>
      expect(environments.action).toHaveBeenCalledWith(
        "env-1",
        "revise",
        { version: 9, reason: undefined, comments: undefined },
        { version: 9, key: expect.any(String) },
      ),
    );
  });
});
