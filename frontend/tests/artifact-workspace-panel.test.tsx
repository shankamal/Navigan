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
