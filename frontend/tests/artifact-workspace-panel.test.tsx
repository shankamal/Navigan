import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ArtifactWorkspacePanel } from "../src/modules/migration-management/artifact-workspace-panel";
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/shared/api/client", () => ({
  apiClient: api,
  writeHeaders: () => ({}),
  normalizeApiError: () => ({ message: "Storage not configured" }),
}));
const props = {
  migrationId: "MIG-one",
  version: 2,
  inventoryDigest: "current",
  namespaces: ["shop", "platform"],
  canEdit: true,
};
beforeEach(() => vi.clearAllMocks());
it("requires scope and does not collect automatically", () => {
  render(<ArtifactWorkspacePanel {...props} />);
  expect(api.get).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", {
      name: "Create workspace",
      hidden: true,
    }),
  ).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});
it("creates only selected snapshot scope", async () => {
  api.post.mockResolvedValue({
    data: {
      workspaceId: "AWS-one",
      namespaces: ["shop"],
      stale: false,
      artifacts: [],
    },
  });
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByLabelText("shop"));
  fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      "/migrations/MIG-one/artifact-workspaces",
      { version: 2, inventoryDigest: "current", namespaces: ["shop"] },
      expect.anything(),
    ),
  );
  expect(
    await screen.findByText(/0 \/ 0 artifacts collected/),
  ).toHaveTextContent("Target readiness not verified");
});
it("reports failure without success", async () => {
  api.post.mockRejectedValue(new Error());
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByLabelText("shop"));
  fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Storage not configured",
  );
  expect(screen.queryByText("Workspace index created")).not.toBeInTheDocument();
});
it("prevents viewer creation", () => {
  render(<ArtifactWorkspacePanel {...props} canEdit={false} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  expect(screen.getByLabelText("shop")).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Create workspace" }),
  ).toBeDisabled();
});

it("queues repository collection for the selected workspace", async () => {
  const workspace = {
    workspaceId: "AWS-one",
    namespaces: ["shop"],
    stale: false,
    status: "PLANNED",
    artifacts: [
      {
        artifactId: "a",
        kind: "REPOSITORY_DEFINITION",
        status: "PENDING_COLLECTION",
      },
    ],
  };
  api.get.mockResolvedValue({ data: { workspaces: [workspace] } });
  api.post.mockResolvedValue({
    data: {
      ...workspace,
      status: "COLLECTING",
      jobs: [{ jobId: "j", status: "QUEUED", attempts: 0 }],
    },
  });
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Collect / retry repository files",
    }),
  );
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      "/migrations/MIG-one/artifact-workspaces/AWS-one/collection-jobs",
      { version: 2 },
      expect.anything(),
    ),
  );
  expect(
    await screen.findByText("Artifact collection queued or running"),
  ).toBeInTheDocument();
});

it("disables collection for an old snapshot", async () => {
  api.get.mockResolvedValue({
    data: {
      workspaces: [
        {
          workspaceId: "AWS-one",
          namespaces: ["shop"],
          stale: true,
          artifacts: [
            {
              artifactId: "a",
              kind: "REPOSITORY_DEFINITION",
              status: "PENDING_COLLECTION",
            },
          ],
        },
      ],
    },
  });
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  expect(
    await screen.findByRole("button", {
      name: "Collect / retry repository files",
    }),
  ).toBeDisabled();
});

it("queues available images separately", async () => {
  const workspace = {
    workspaceId: "AWS-one",
    namespaces: ["shop"],
    stale: false,
    status: "PLANNED",
    artifacts: [
      { artifactId: "image", kind: "IMAGE", status: "PENDING_COLLECTION" },
    ],
  };
  api.get.mockResolvedValue({ data: { workspaces: [workspace] } });
  api.post.mockResolvedValue({
    data: { ...workspace, status: "COLLECTING", jobs: [] },
  });
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Collect / retry available images",
    }),
  );
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      "/migrations/MIG-one/artifact-workspaces/AWS-one/collection-jobs",
      { version: 2, artifactKind: "IMAGE" },
      expect.anything(),
    ),
  );
});

it("keeps missing images in recovery", async () => {
  api.get.mockResolvedValue({
    data: {
      workspaces: [
        {
          workspaceId: "AWS-one",
          namespaces: ["shop"],
          stale: false,
          artifacts: [
            { artifactId: "image", kind: "IMAGE", status: "RECOVERY_REQUIRED" },
          ],
        },
      ],
    },
  });
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  expect(
    await screen.findByRole("button", {
      name: "Collect / retry available images",
    }),
  ).toBeDisabled();
});

it("preserves selections while searching and lets the user clear the full scope", () => {
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByLabelText("shop"));
  fireEvent.change(
    screen.getByRole("searchbox", { name: "Search namespaces" }),
    { target: { value: "platform" } },
  );
  expect(screen.queryByLabelText("shop")).not.toBeInTheDocument();
  expect(screen.getByText("1 of 2 selected")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Select all" }));
  expect(screen.getByText("2 of 2 selected")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
  expect(
    screen.getByRole("button", { name: "Create workspace" }),
  ).toBeDisabled();
});

it("separates saved artifacts, pending collection, and recovery in its summary", async () => {
  api.get.mockResolvedValue({
    data: {
      workspaces: [
        {
          workspaceId: "AWS-one",
          namespaces: ["shop"],
          stale: false,
          status: "PARTIAL",
          artifacts: [
            {
              artifactId: "a",
              kind: "REPOSITORY_DEFINITION",
              status: "COLLECTED",
            },
            { artifactId: "b", kind: "IMAGE", status: "PENDING_COLLECTION" },
            {
              artifactId: "c",
              kind: "LIVE_DEFINITION",
              status: "EXPORT_REQUIRED",
            },
          ],
        },
      ],
    },
  });
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  expect(await screen.findByText("Partially collected")).toBeInTheDocument();
  const metrics = screen.getByLabelText("Artifact collection progress");
  expect(metrics).toHaveTextContent(
    "3Required artifacts1Saved to S31Awaiting collection1Needs attention",
  );
  fireEvent.click(screen.getByText("View required files, images & status"));
  expect(
    screen.getByText("Export definition from source cluster"),
  ).toBeInTheDocument();
});

it("exports a selected live definition and checks its progress in the same workspace", async () => {
  const artifact = {
    artifactId: "live-one",
    kind: "LIVE_DEFINITION",
    status: "EXPORT_REQUIRED",
    source: {
      resource: { namespace: "shop", kind: "Deployment", name: "api" },
    },
    validation: {} as { recovery?: { jobId: string; status: string } },
  };
  const workspace = {
    workspaceId: "AWS-one",
    namespaces: ["shop"],
    stale: false,
    artifacts: [artifact],
  };
  api.get.mockResolvedValue({ data: { workspaces: [workspace] } });
  api.post.mockImplementation(async () => {
    artifact.status = "RECOVERING";
    artifact.validation.recovery = { jobId: "REC-one", status: "RECOVERING" };
    return { data: { job: artifact.validation.recovery } };
  });
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  fireEvent.click(
    await screen.findByText("View required files, images & status"),
  );
  expect(screen.getByText("shop / Deployment / api")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Export live definition" }),
  );
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      "/migrations/MIG-one/deployment-evidence",
      {
        version: 2,
        recovery: {
          operation: "START",
          workspaceId: "AWS-one",
          artifactId: "live-one",
        },
      },
      expect.anything(),
    ),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Check recovery progress" }),
  );
  await waitFor(() =>
    expect(api.post).toHaveBeenLastCalledWith(
      "/migrations/MIG-one/deployment-evidence",
      {
        version: 2,
        recovery: {
          operation: "POLL",
          workspaceId: "AWS-one",
          artifactId: "live-one",
          jobId: "REC-one",
        },
      },
      expect.anything(),
    ),
  );
});

it("shows saved recovered Helm data as requiring review", async () => {
  api.get.mockResolvedValue({
    data: {
      workspaces: [
        {
          workspaceId: "AWS-one",
          namespaces: ["shop"],
          stale: false,
          artifacts: [
            {
              artifactId: "helm",
              kind: "HELM_RELEASE",
              status: "COLLECTED",
              source: { namespace: "shop", release: "app" },
              validation: { reviewRequired: true },
            },
          ],
        },
      ],
    },
  });
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  fireEvent.click(
    await screen.findByText("View required files, images & status"),
  );
  expect(screen.getByText("shop / app")).toBeInTheDocument();
  expect(screen.getByText(/Recovered copy: review/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Recover Helm release" }),
  ).not.toBeInTheDocument();
});

const recoveryWorkspace = () => ({
  workspaceId: "AWS-one",
  namespaces: ["shop"],
  stale: false,
  artifacts: [
    {
      artifactId: "live-one",
      kind: "LIVE_DEFINITION",
      status: "EXPORT_REQUIRED",
      source: {
        resource: { namespace: "shop", kind: "Deployment", name: "api" },
      },
    },
  ],
});
async function openRecovery() {
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  fireEvent.click(
    await screen.findByText("View required files, images & status"),
  );
  return screen.getByRole("button", { name: "Export live definition" });
}

it("shows a failed recovery request beside the clicked artifact", async () => {
  api.get.mockResolvedValue({ data: { workspaces: [recoveryWorkspace()] } });
  api.post.mockRejectedValue(new Error("denied"));
  const button = await openRecovery();
  const row = button.closest("tr")!;
  fireEvent.click(button);
  const alert = await screen.findByRole("alert");
  expect(row).toContainElement(alert);
  expect(alert).toHaveTextContent("Storage not configured");
  expect(button).toBeEnabled();
});

it("shows starting progress immediately while recovery is being requested", async () => {
  api.get.mockResolvedValue({ data: { workspaces: [recoveryWorkspace()] } });
  let reject!: (error: Error) => void;
  api.post.mockImplementation(
    () =>
      new Promise((_, fail) => {
        reject = fail;
      }),
  );
  const button = await openRecovery();
  const row = button.closest("tr")!;
  fireEvent.click(button);
  expect(row).toHaveTextContent("Starting source recovery…");
  expect(button).toBeDisabled();
  reject(new Error("denied"));
  await screen.findByRole("alert");
});

it("retains the accepted recovery handle when workspace refresh fails", async () => {
  api.get
    .mockResolvedValueOnce({ data: { workspaces: [recoveryWorkspace()] } })
    .mockRejectedValue(new Error("refresh failed"));
  api.post.mockResolvedValue({
    data: { job: { jobId: "REC-accepted", status: "RECOVERING" } },
  });
  fireEvent.click(await openRecovery());
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Recovery response received, but the workspace could not refresh",
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Check recovery progress" }),
  );
  await waitFor(() =>
    expect(api.post).toHaveBeenLastCalledWith(
      "/migrations/MIG-one/deployment-evidence",
      {
        version: 2,
        recovery: {
          operation: "POLL",
          workspaceId: "AWS-one",
          artifactId: "live-one",
          jobId: "REC-accepted",
        },
      },
      expect.anything(),
    ),
  );
});

function historicalWorkspace() {
  const parent = {
    apiVersion: "batch/v1",
    kind: "CronJob",
    namespace: "shop",
    name: "check",
  };
  return {
    workspaceId: "AWS-one",
    namespaces: ["shop"],
    stale: false,
    artifacts: [
      {
        artifactId: "job",
        kind: "LIVE_DEFINITION",
        status: "RECOVERY_REQUIRED",
        source: {
          resource: { namespace: "shop", kind: "Job", name: "check-123" },
        },
        validation: {
          recovery: { jobId: "REC-failed", status: "CUSTOMER_INPUT_REQUIRED" },
        },
      },
      {
        artifactId: "definition",
        kind: "REPOSITORY_DEFINITION",
        status: "COLLECTED",
        source: { filePath: "operations.yaml" },
        workloads: [parent],
      },
      {
        artifactId: "image",
        kind: "IMAGE",
        status: "COLLECTED",
        workloads: [parent],
      },
    ],
  };
}
async function openHistoricalReview() {
  render(<ArtifactWorkspacePanel {...props} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  fireEvent.click(
    await screen.findByText("View required files, images & status"),
  );
  fireEvent.click(screen.getByText("Review deleted Job run"));
}

it("requires a selected saved CronJob and confirmation before recording a historical exclusion", async () => {
  const workspace = historicalWorkspace();
  api.get.mockResolvedValue({ data: { workspaces: [workspace] } });
  const completed = {
    ...workspace,
    artifacts: workspace.artifacts.map((a) =>
      a.artifactId === "job"
        ? {
            ...a,
            status: "EXCLUDED_FROM_REPLAY",
            validation: {
              ...a.validation,
              historicalReview: {
                parent: { kind: "CronJob", namespace: "shop", name: "check" },
                reviewedAt: "2026-10-22",
              },
            },
          }
        : a,
    ),
  };
  api.post.mockResolvedValue({ data: { workspace: completed } });
  await openHistoricalReview();
  const button = screen.getByRole("button", {
    name: "Record historical exclusion",
  });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Saved parent CronJob"), {
    target: {
      value: JSON.stringify({ artifactId: "definition", name: "check" }),
    },
  });
  expect(button).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText(
      "I checked that this is a deleted historical run of the selected CronJob.",
    ),
  );
  fireEvent.click(button);
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      "/migrations/MIG-one/deployment-evidence",
      {
        version: 2,
        recovery: {
          operation: "EXCLUDE_HISTORICAL_JOB",
          workspaceId: "AWS-one",
          artifactId: "job",
          parentArtifactId: "definition",
          parentCronJobName: "check",
          confirmHistoricalRun: true,
        },
      },
      expect.anything(),
    ),
  );
  expect(
    await screen.findByText(/2 \/ 2 artifacts collected/),
  ).toHaveTextContent("Target readiness not verified");
  expect(
    screen.getByText("Historical run · Excluded from replay"),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/1 historical Job run excluded from replay/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Export live definition" }),
  ).not.toBeInTheDocument();
});

it("keeps a historical Job unresolved if saving its review fails", async () => {
  api.get.mockResolvedValue({ data: { workspaces: [historicalWorkspace()] } });
  api.post.mockRejectedValue(new Error("receipt failed"));
  await openHistoricalReview();
  fireEvent.change(screen.getByLabelText("Saved parent CronJob"), {
    target: {
      value: JSON.stringify({ artifactId: "definition", name: "check" }),
    },
  });
  fireEvent.click(
    screen.getByLabelText(
      "I checked that this is a deleted historical run of the selected CronJob.",
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Record historical exclusion" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Storage not configured",
  );
  expect(
    screen.queryByText("Historical run · Excluded from replay"),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Export live definition" }),
  ).toBeEnabled();
});

it("clears historical confirmation when the parent selection changes", async () => {
  api.get.mockResolvedValue({ data: { workspaces: [historicalWorkspace()] } });
  await openHistoricalReview();
  const select = screen.getByLabelText("Saved parent CronJob");
  fireEvent.change(select, {
    target: {
      value: JSON.stringify({ artifactId: "definition", name: "check" }),
    },
  });
  const confirm = screen.getByLabelText(
    "I checked that this is a deleted historical run of the selected CronJob.",
  );
  fireEvent.click(confirm);
  expect(
    screen.getByRole("button", { name: "Record historical exclusion" }),
  ).toBeEnabled();
  fireEvent.change(select, { target: { value: "" } });
  expect(confirm).not.toBeChecked();
  expect(
    screen.getByRole("button", { name: "Record historical exclusion" }),
  ).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});

function readyExportWorkspace() {
  return {
    workspaceId: "AWS-one",
    namespaces: ["shop"],
    stale: false,
    artifacts: [
      {
        artifactId: "definition",
        kind: "REPOSITORY_DEFINITION",
        status: "COLLECTED",
      },
      { artifactId: "image", kind: "IMAGE", status: "COLLECTED" },
      {
        artifactId: "historical",
        kind: "LIVE_DEFINITION",
        status: "EXCLUDED_FROM_REPLAY",
      },
    ],
  };
}
async function openExportWorkspace(canEdit = true) {
  render(<ArtifactWorkspacePanel {...props} canEdit={canEdit} />);
  fireEvent.click(screen.getByText("Migration files & images"));
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  return screen.findByRole("button", { name: "Create workspace export" });
}
const exportedManifest = {
  exportId: "EXP-one",
  downloadUrl: "https://private.example/export.json?versionId=one",
  expiresInSeconds: 300,
  collectedArtifactCount: 2,
  excludedArtifactCount: 1,
  storage: { versionId: "one", sha256: "a".repeat(64) },
};

it("creates and downloads a version-pinned export while retaining target review limits", async () => {
  api.get.mockResolvedValue({ data: { workspaces: [readyExportWorkspace()] } });
  api.post.mockResolvedValue({ data: exportedManifest });
  fireEvent.click(await openExportWorkspace());
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      "/migrations/MIG-one/artifact-workspaces/AWS-one/exports",
      { version: 2 },
      expect.anything(),
    ),
  );
  const download = await screen.findByRole("link", {
    name: "Download export manifest",
  });
  expect(download).toHaveAttribute("href", exportedManifest.downloadUrl);
  expect(screen.getByText(/Export saved to S3/)).toHaveTextContent(
    "2 collected artifacts · 1 historical exclusions · Target readiness not verified",
  );
  expect(screen.getByText(/EXP-one · SHA-256:/)).toHaveTextContent(
    "a".repeat(64),
  );
});

it("does not offer a download when export verification fails", async () => {
  api.get.mockResolvedValue({ data: { workspaces: [readyExportWorkspace()] } });
  api.post.mockRejectedValue(new Error("object missing"));
  fireEvent.click(await openExportWorkspace());
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Storage not configured",
  );
  expect(
    screen.queryByRole("link", { name: "Download export manifest" }),
  ).not.toBeInTheDocument();
});

it("prevents export while a required artifact remains unresolved", async () => {
  const workspace = readyExportWorkspace();
  workspace.artifacts[0].status = "PENDING_COLLECTION";
  api.get.mockResolvedValue({ data: { workspaces: [workspace] } });
  expect(await openExportWorkspace()).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});

it("prevents a viewer from creating an export", async () => {
  api.get.mockResolvedValue({ data: { workspaces: [readyExportWorkspace()] } });
  expect(await openExportWorkspace(false)).toBeDisabled();
});

it("explains expired download links without following them", async () => {
  const clock = vi.spyOn(Date, "now").mockReturnValue(1000);
  try {
    api.get.mockResolvedValue({
      data: { workspaces: [readyExportWorkspace()] },
    });
    api.post.mockResolvedValue({ data: exportedManifest });
    fireEvent.click(await openExportWorkspace());
    const download = await screen.findByRole("link", {
      name: "Download export manifest",
    });
    clock.mockReturnValue(302000);
    expect(fireEvent.click(download)).toBe(false);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The download link expired",
    );
  } finally {
    clock.mockRestore();
  }
});

it("loads saved workspaces only when the guided view opens and never collects implicitly", async () => {
  api.get.mockResolvedValue({
    data: {
      workspaces: [
        {
          workspaceId: "AWS-existing",
          namespaces: ["shop"],
          stale: false,
          artifacts: [],
        },
      ],
    },
  });
  const { rerender } = render(
    <ArtifactWorkspacePanel {...props} guided active={false} />,
  );
  expect(api.get).not.toHaveBeenCalled();
  rerender(<ArtifactWorkspacePanel {...props} guided active />);
  await screen.findByText("Workspace index created");
  expect(api.get).toHaveBeenCalledTimes(1);
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByText("Create another workspace")).toBeVisible();
  rerender(<ArtifactWorkspacePanel {...props} guided active={false} />);
  rerender(<ArtifactWorkspacePanel {...props} guided active />);
  expect(api.get).toHaveBeenCalledTimes(1);
});

it("provides a retry after saved-workspace loading fails without creating anything", async () => {
  api.get.mockRejectedValueOnce(new Error("unavailable"));
  render(<ArtifactWorkspacePanel {...props} guided active />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Storage not configured",
  );
  api.get.mockResolvedValueOnce({ data: { workspaces: [] } });
  fireEvent.click(screen.getByRole("button", { name: "Load workspaces" }));
  await screen.findByText(/No saved workspaces yet/);
  expect(api.post).not.toHaveBeenCalled();
});
