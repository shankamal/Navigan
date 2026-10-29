import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewClusterPage } from "@/modules/cluster-management";
import { clusters } from "@/modules/cluster-management/service";
import { environments } from "@/modules/environment-management/services/environments";
const fixture = vi.hoisted(() => ({
  environment: {
    environmentId: "ENV-approved",
    environmentName: "Dev environment",
    customerId: "CUS-active",
    customerName: "Active customer",
    approvedVersion: 9,
    approvedStatus: "ACTIVE",
    status: "DRAFT",
    configuration: {
      account: { accountId: "123456789012" },
      location: { region: "ap-south-1" },
      network: {
        vpc: { vpcId: "vpc-one" },
        clusterSubnets: [],
        nodeSubnets: [],
      },
      extensions: {
        provisioningContract: {
          kubernetesVersions: [
            { version: "1.33", support: "STANDARD_SUPPORT" },
            { version: "1.34", support: "UNSUPPORTED" },
          ],
          instanceTypes: ["t3.medium"],
          provisioningRoles: [],
          provisioningSecrets: [],
        },
      },
    },
  },
}));
const navigation = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("@/modules/cluster-management/service", () => ({
  clusters: { create: vi.fn() },
}));
vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: null }),
}));
vi.mock("@/modules/customer-management/services/customers", () => ({
  customersService: {
    list: vi.fn(async () => ({
      items: [{ customerId: "CUS-active", name: "Active customer" }],
    })),
  },
}));
vi.mock("@/modules/environment-management/services/environments", () => ({
  environments: {
    list: vi.fn(async () => ({ items: [fixture.environment] })),
    version: vi.fn(async () => fixture.environment),
    provisioningOptions: vi.fn(async () => ({ provisioningSecrets: [] })),
  },
}));
function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <NewClusterPage />
    </QueryClientProvider>,
  );
}
async function selectCustomer() {
  // Customer options are loaded after the active-customer search is entered.
  fireEvent.change(
    screen.getByPlaceholderText("Search active customers by name"),
    {
      target: { value: "Active" },
    },
  );
  await screen.findByRole("option", { name: "Active customer" });
  fireEvent.change(screen.getByRole("combobox", { name: /Customer/i }), {
    target: { value: "CUS-active" },
  });
}
beforeEach(() => {
  vi.mocked(clusters.create)
    .mockReset()
    .mockResolvedValue({ clusterId: "CLU-created" } as never);
  navigation.push.mockClear();
  vi.mocked(environments.list)
    .mockReset()
    .mockResolvedValue({ items: [fixture.environment] } as never);
  vi.mocked(environments.version)
    .mockReset()
    .mockResolvedValue(fixture.environment as never);
});
describe("New cluster setup dependent loading", () => {
  it("loads the active approved environment and supported versions from its pinned snapshot even while a new draft exists", async () => {
    mount();
    await selectCustomer();
    const option = await screen.findByRole("option", {
      name: /Dev environment.*approved v9/,
    });
    expect(option).toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("combobox", { name: /^Active environment/ }),
      { target: { value: "ENV-approved" } },
    );
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: /^Kubernetes version/ }),
      ).toHaveValue("1.33"),
    );
    expect(environments.version).toHaveBeenCalledWith("ENV-approved", 9);
    expect(
      screen.queryByRole("option", { name: "1.34" }),
    ).not.toBeInTheDocument();
    expect(environments.list).toHaveBeenCalledWith(
      expect.objectContaining({
        customerId: "CUS-active",
        approvedStatus: "ACTIVE",
        cloudProvider: "AWS",
      }),
    );
  });
  it("shows a failed environment request and lets the user retry instead of claiming no environments exist", async () => {
    vi.mocked(environments.list).mockRejectedValueOnce(
      new Error("Environment API unavailable"),
    );
    mount();
    await selectCustomer();
    await screen.findByText("Environment API unavailable");
    expect(
      screen.queryByText(
        "This customer has no active approved AWS/EKS baselines yet.",
      ),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Reload active environments" }),
    );
    await screen.findByRole("option", { name: /Dev environment.*approved v9/ });
  });
  it("explains a missing approved version contract without inventing selectable Kubernetes versions", async () => {
    vi.mocked(environments.version).mockResolvedValue({
      ...fixture.environment,
      configuration: {
        ...fixture.environment.configuration,
        extensions: { provisioningContract: { kubernetesVersions: [] } },
      },
    } as never);
    mount();
    await selectCustomer();
    await screen.findByRole("option", { name: /Dev environment.*approved v9/ });
    fireEvent.change(
      screen.getByRole("combobox", { name: /^Active environment/ }),
      { target: { value: "ENV-approved" } },
    );
    await screen.findByText(
      /has no supported Kubernetes versions in its provisioning contract/,
    );
    expect(
      screen.getByRole("combobox", { name: /^Kubernetes version/ }),
    ).toBeDisabled();
  });
});

async function completeSetup(withName = true) {
  vi.mocked(environments.version).mockResolvedValue({
    ...fixture.environment,
    configuration: {
      ...fixture.environment.configuration,
      extensions: {
        provisioningContract: {
          ...fixture.environment.configuration.extensions.provisioningContract,
          provisioningRoles: [
            { roleName: "Provisioner", roleArn: "arn:approved-role" },
          ],
          provisioningSecrets: [
            { name: "Registered External ID", arn: "arn:registered-secret" },
          ],
        },
      },
    },
  } as never);
  mount();
  await selectCustomer();
  await screen.findByRole("option", { name: /Dev environment.*approved v9/ });
  fireEvent.change(
    screen.getByRole("combobox", { name: /^Active environment/ }),
    { target: { value: "ENV-approved" } },
  );
  await waitFor(() =>
    expect(
      screen.getByRole("combobox", { name: /^Kubernetes version/ }),
    ).toHaveValue("1.33"),
  );
  if (withName)
    fireEvent.change(screen.getByRole("textbox", { name: "Cluster name *" }), {
      target: { value: "platform-dev" },
    });
  fireEvent.click(screen.getByRole("link", { name: /System workers/ }));
  fireEvent.change(screen.getByRole("textbox", { name: /^Node group name/ }), {
    target: { value: "custom-system" },
  });
  fireEvent.change(
    screen.getByRole("combobox", { name: /^EC2 instance type/ }),
    { target: { value: "t3.medium" } },
  );
  expect(
    screen.getByRole("combobox", { name: /^Capacity type/ }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("link", { name: /Repository & access/ }));
  fireEvent.change(
    screen.getByRole("textbox", { name: /^GitHub organization/ }),
    { target: { value: "Example-Org" } },
  );
  fireEvent.click(
    document.querySelector("#cluster-provisioning-access > summary")!,
  );
  fireEvent.change(
    screen.getByRole("combobox", { name: /^Provisioning role ARN/ }),
    { target: { value: "arn:approved-role" } },
  );
  fireEvent.change(
    screen.getByRole("combobox", { name: /^External ID secret ARN/ }),
    { target: { value: "arn:registered-secret" } },
  );
}
describe("Cluster setup studio", () => {
  it("retains worker edits when switching sections and blocks inconsistent scaling", async () => {
    await completeSetup();
    fireEvent.click(screen.getByRole("link", { name: /System workers/ }));
    expect(
      screen.getByRole("textbox", { name: /^Node group name/ }),
    ).toHaveValue("custom-system");
    expect(
      screen.getByRole("combobox", { name: /^EC2 instance type/ }),
    ).toHaveValue("t3.medium");
    fireEvent.change(
      screen.getByRole("spinbutton", { name: /^Desired nodes/ }),
      { target: { value: "5" } },
    );
    expect(
      screen.getByRole("button", { name: "Save setup request draft" }),
    ).toBeDisabled();
    expect(clusters.create).not.toHaveBeenCalled();
  });
  it("saves the original pinned approved-version request and protected system pool", async () => {
    await completeSetup();
    fireEvent.click(
      screen.getByRole("button", { name: "Save setup request draft" }),
    );
    await waitFor(() => expect(clusters.create).toHaveBeenCalledTimes(1));
    expect(clusters.create).toHaveBeenCalledWith(
      expect.objectContaining({
        environmentId: "ENV-approved",
        environmentApprovedVersion: 9,
        clusterName: "platform-dev",
        kubernetesVersion: "1.33",
        endpointAccess: "PRIVATE",
        githubOrganization: "Example-Org",
        provisioningRoleArn: "arn:approved-role",
        externalIdSecretArn: "arn:registered-secret",
        nodeGroups: [
          expect.objectContaining({
            name: "custom-system",
            purpose: "SYSTEM",
            capacityType: "ON_DEMAND",
            instanceTypes: ["t3.medium"],
            minSize: 2,
            desiredSize: 2,
            maxSize: 4,
            diskSizeGiB: 50,
          }),
        ],
      }),
    );
    await waitFor(() =>
      expect(navigation.push).toHaveBeenCalledWith("/clusters/CLU-created"),
    );
  });
  it("reveals a required field inside a collapsed section before native validation", async () => {
    await completeSetup(false);
    expect(
      document.querySelector("#cluster-configuration"),
    ).not.toHaveAttribute("open");
    fireEvent.click(
      screen.getByRole("button", { name: "Save setup request draft" }),
    );
    expect(document.querySelector("#cluster-configuration")).toHaveAttribute(
      "open",
    );
    expect(
      screen.getByRole("textbox", { name: "Cluster name *" }),
    ).toBeInvalid();
    expect(clusters.create).not.toHaveBeenCalled();
  });
});
