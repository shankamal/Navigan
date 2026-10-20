import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { vi, it, expect } from "vitest";
import {
  DeploymentStructure,
  ArtifactResolution,
} from "../src/modules/migration-management/deployment-structure";
import type { DeploymentWorkloadEvidence } from "../src/modules/migration-management/deployment-evidence-service";
const api = vi.hoisted(() => ({ recover: vi.fn() }));
vi.mock(
  "../src/modules/migration-management/deployment-evidence-service",
  () => ({ deploymentDiscovery: api }),
);
const digest = "sha256:" + "a".repeat(64);
const workload = {
  workload: {
    apiVersion: "apps/v1",
    kind: "Deployment",
    namespace: "shop",
    name: "api",
  },
  applicationVersion: null,
  artifactFormat: "Unresolved",
  deliveryTool: "Unresolved",
  helmChart: null,
  helmRelease: null,
  mappingStatus: "UNRESOLVED",
  runtimeStatus: "OBSERVED",
  candidates: [],
  containers: [
    {
      name: "main",
      containerType: "APPLICATION",
      configuredImage: "example/app@" + digest,
      runningImageIDs: [],
      observedDigests: [],
      runningImages: [],
      runningPodCount: 1,
      multipleRunningVersions: false,
      digestComparison: "UNVERIFIED",
      registryEvidence: {
        image: "example/app@" + digest,
        status: "NOT_FOUND",
        reason: "Not found at registry endpoint.",
      },
    },
    {
      name: "setup",
      containerType: "INIT",
      configuredImage: "example/setup:v1",
      observedDigests: [],
      runningImageIDs: [],
      runningImages: [],
      runningPodCount: 0,
      multipleRunningVersions: false,
      digestComparison: "UNVERIFIED",
      registryEvidence: null,
    },
  ],
  gaps: [],
} as DeploymentWorkloadEvidence;
it("shows init images and separates declared from missing runtime digest", () => {
  render(
    <DeploymentStructure
      workloads={[workload]}
      onInspect={vi.fn()}
      onResolve={vi.fn()}
    />,
  );
  expect(screen.getByText("setup")).toBeVisible();
  expect(screen.getByText("Init container")).toBeVisible();
  fireEvent.click(screen.getByText("main"));
  expect(
    within(screen.getByText("main").closest("details")!).getByText(
      "Not reported by the collected runtime evidence",
    ),
  ).toBeVisible();
  expect(screen.getByText(/No original repository mapping/)).toBeVisible();
  expect(screen.getByText(digest)).toBeVisible();
});
it("starts recovery only when asked and sends a discovered digest", async () => {
  api.recover.mockResolvedValue({
    job: {
      jobId: "REC-test",
      kind: "IMAGE",
      workload: workload.workload,
      inventoryDigest: "inventory",
      status: "CUSTOMER_INPUT_REQUIRED",
      message: "Cache unavailable on configured host.",
    },
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ArtifactResolution
        migrationId="MIG-test"
        version={2}
        inventoryDigest="inventory"
        workload={workload}
        container={workload.containers[0]}
        jobs={[]}
        canEdit
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
  expect(api.recover).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Check cache and recover" }),
  );
  await waitFor(() =>
    expect(api.recover).toHaveBeenCalledWith(
      "MIG-test",
      2,
      expect.objectContaining({
        operation: "START",
        digest,
        containerName: "main",
        namespace: "shop",
      }),
    ),
  );
  expect(
    await screen.findByText("Cache unavailable on configured host."),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Download recovered artifact" }),
  ).not.toBeInTheDocument();
});
it("requires digest identity and edit permission", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ArtifactResolution
        migrationId="MIG-test"
        version={2}
        inventoryDigest="inventory"
        workload={workload}
        container={workload.containers[1]}
        jobs={[]}
        canEdit={false}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
  expect(
    screen.getByRole("button", { name: "Check cache and recover" }),
  ).toBeDisabled();
  expect(screen.getByText(/No recoverable digest identity/)).toBeVisible();
});
