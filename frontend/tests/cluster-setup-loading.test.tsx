import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewClusterPage } from "@/modules/cluster-management";
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
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
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
  await screen.findByRole("option", { name: "Active customer" });
  fireEvent.change(screen.getByRole("combobox", { name: /Customer/i }), {
    target: { value: "CUS-active" },
  });
}
beforeEach(() => {
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
