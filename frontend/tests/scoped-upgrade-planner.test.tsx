import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ScopedUpgradePlanner } from "../src/modules/upgrade-management/scoped-upgrade-planner";
import {
  planScopes,
  planVersionLabel,
} from "../src/modules/upgrade-management/plan-scope";
import { scheduleOverdue } from "../src/modules/upgrade-management/schedule-state";
import type { UpgradeCluster } from "../src/modules/upgrade-management/upgrade-workspace";
import type { EksUpgradePlan } from "../src/modules/cluster-management/model";
const mocks = vi.hoisted(() => ({
  options: vi.fn(),
  create: vi.fn(),
  change: vi.fn(),
  privileges: ["cluster.upgrade.plan"],
}));
vi.mock("@/modules/cluster-management/service", () => ({
  clusters: {
    upgradeOptions: mocks.options,
    createScopedUpgradePlan: mocks.create,
    changeUpgradePlan: mocks.change,
  },
}));
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({
    identity: {
      subject: "engineer",
      privileges: mocks.privileges,
      roles: ["CLOUD_ENGINEER"],
    },
  }),
}));
vi.mock("../src/modules/upgrade-management/cluster-context", () => ({
  ClusterContext: () => <p>Customer · Account · Environment · Cluster</p>,
}));
const options = {
  clusterId: "CLU-one",
  provider: "EKS",
  region: "ap-south-1",
  currentVersion: "1.34",
  status: "ACTIVE",
  targetVersions: ["1.35", "1.36", "1.37"],
  nodeGroups: [
    { name: "lagging", version: "1.33", status: "ACTIVE" },
    { name: "aligned", version: "1.34", status: "ACTIVE" },
  ],
  addons: [
    {
      name: "cni",
      version: "v1.1.0",
      status: "ACTIVE",
      versions: [{ version: "v1.2.0", recommended: true }],
    },
  ],
  nodeUpgradeNote: "Align selected nodes.",
  observedAt: "2026-11-11T10:00:00Z",
};
function mount() {
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
      <ScopedUpgradePlanner
        cluster={
          {
            id: "CLU-one",
            name: "Demo",
            environment: "Prod",
            provider: "EKS",
          } as UpgradeCluster
        }
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  mocks.options.mockReset().mockResolvedValue(options);
  mocks.create
    .mockReset()
    .mockResolvedValue({ planId: "UPG-one", status: "DRAFT", version: 1 });
  mocks.change.mockReset();
  mocks.privileges = ["cluster.upgrade.plan"];
});
describe("Scoped upgrade planner", () => {
  it("permits node-only planning without a newer control-plane version", async () => {
    mocks.options.mockResolvedValue({ ...options, targetVersions: [] });
    mount();
    fireEvent.click(await screen.findByRole("radio", { name: "Node groups" }));
    expect(screen.getByLabelText(/aligned · 1.34/)).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/lagging · 1.33/));
    fireEvent.change(
      screen.getByRole("textbox", { name: "3. Change reason" }),
      { target: { value: "Align the selected node group" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save draft & review" }),
    );
    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith("CLU-one", {
        upgradeScope: "NODES",
        nodeGroups: ["lagging"],
        hopWindows: [],
        changeReason: "Align the selected node group",
      }),
    );
    expect(mocks.change).not.toHaveBeenCalled();
  });
  it("sends only selected add-ons and compatible targets", async () => {
    mount();
    fireEvent.click(
      await screen.findByRole("radio", { name: "Managed add-ons" }),
    );
    fireEvent.change(screen.getByRole("combobox", { name: /cni/ }), {
      target: { value: "v1.2.0" },
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "3. Change reason" }),
      { target: { value: "Upgrade CNI compatibility" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Save draft & review" }),
    );
    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith(
        "CLU-one",
        expect.objectContaining({
          upgradeScope: "ADDONS",
          addons: { cni: "v1.2.0" },
        }),
      ),
    );
  });
  it("shows every intermediate minor and requires all supplied windows", async () => {
    mount();
    fireEvent.change(
      await screen.findByRole("combobox", { name: "Final Kubernetes target" }),
      { target: { value: "1.37" } },
    );
    expect(
      screen.getByText("Upgrade path: 1.34 → 1.35 → 1.36 → 1.37"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Step 3 maintenance start"),
    ).toBeInTheDocument();
    fireEvent.change(
      screen.getByRole("textbox", { name: "3. Change reason" }),
      { target: { value: "Upgrade through all supported versions" } },
    );
    fireEvent.change(screen.getByLabelText("Step 1 maintenance start"), {
      target: { value: "2027-02-01T10:00" },
    });
    expect(
      screen.getByRole("button", { name: "Save draft & review" }),
    ).toBeDisabled();
    for (const i of [2, 3])
      fireEvent.change(screen.getByLabelText(`Step ${i} maintenance start`), {
        target: { value: `2027-02-0${i}T10:00` },
      });
    expect(
      screen.getByRole("button", { name: "Save draft & review" }),
    ).toBeEnabled();
  });
  it("keeps dynamic denial authoritative even with the Cloud Engineer role label", async () => {
    mocks.privileges = [];
    mount();
    await screen.findByRole("radio", { name: "Cluster version" });
    fireEvent.change(
      screen.getByRole("textbox", { name: "3. Change reason" }),
      { target: { value: "Upgrade the cluster" } },
    );
    expect(
      screen.getByRole("button", { name: "Save draft & review" }),
    ).toBeDisabled();
  });
  it("shows discovery failures without enabling save", async () => {
    mocks.options.mockRejectedValue(new Error("Customer role cannot read EKS"));
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Customer role cannot read EKS",
    );
    expect(
      screen.getByRole("button", { name: "Save draft & review" }),
    ).toBeDisabled();
  });
  it("classifies component plans from their exact operations", () => {
    const p = {
      kind: "CONTAINER",
      currentVersion: "1.34",
      targetVersion: "1.34",
      planSpec: {
        scope: "ADDONS",
        steps: [
          {
            operations: [
              { kind: "ADDON", name: "cni", from: "v1.1.0", to: "v1.2.0" },
            ],
          },
        ],
      },
    } as EksUpgradePlan;
    expect(planScopes(p)).toEqual(["addons"]);
    expect(planVersionLabel(p)).toBe("v1.1.0 → v1.2.0");
  });
  it("expires approved steps at the window end instead of its start", () => {
    const p = {
      status: "SCHEDULED",
      scheduledFor: "2027-02-01T10:00:00Z",
      planSpec: {
        steps: [
          {
            window: {
              scheduledFor: "2027-02-01T10:00:00Z",
              durationMinutes: 120,
            },
          },
        ],
      },
      execution: { hopIndex: 0 },
    };
    expect(scheduleOverdue(p, Date.parse("2027-02-01T11:00:00Z"))).toBe(false);
    expect(scheduleOverdue(p, Date.parse("2027-02-01T12:00:00Z"))).toBe(true);
  });
});
