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
      name: "Create workspace index",
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
  fireEvent.click(screen.getByText("Artifact workspace"));
  fireEvent.click(screen.getByLabelText("shop"));
  fireEvent.click(
    screen.getByRole("button", { name: "Create workspace index" }),
  );
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
  fireEvent.click(screen.getByText("Artifact workspace"));
  fireEvent.click(screen.getByLabelText("shop"));
  fireEvent.click(
    screen.getByRole("button", { name: "Create workspace index" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Storage not configured",
  );
  expect(screen.queryByText("Workspace index created")).not.toBeInTheDocument();
});
it("prevents viewer creation", () => {
  render(<ArtifactWorkspacePanel {...props} canEdit={false} />);
  fireEvent.click(screen.getByText("Artifact workspace"));
  expect(screen.getByLabelText("shop")).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Create workspace index" }),
  ).toBeDisabled();
});

it("queues repository collection for the selected workspace", async () => {
  const workspace = {workspaceId:"AWS-one",namespaces:["shop"],stale:false,status:"PLANNED",artifacts:[{artifactId:"a",kind:"REPOSITORY_DEFINITION",status:"PENDING_COLLECTION"}]};
  api.get.mockResolvedValue({data:{workspaces:[workspace]}});
  api.post.mockResolvedValue({data:{...workspace,status:"COLLECTING",jobs:[{jobId:"j",status:"QUEUED",attempts:0}]}});
  render(<ArtifactWorkspacePanel {...props}/>);
  fireEvent.click(screen.getByText("Artifact workspace"));
  fireEvent.click(screen.getByRole("button",{name:"Load workspaces"}));
  fireEvent.click(await screen.findByRole("button",{name:"Collect / retry repository files"}));
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/migrations/MIG-one/artifact-workspaces/AWS-one/collection-jobs',{version:2},expect.anything()));
  expect(await screen.findByText("Repository collection queued or running")).toBeInTheDocument();
});

it("disables collection for an old snapshot", async () => {
 api.get.mockResolvedValue({data:{workspaces:[{workspaceId:"AWS-one",namespaces:["shop"],stale:true,artifacts:[{artifactId:"a",kind:"REPOSITORY_DEFINITION",status:"PENDING_COLLECTION"}]}]}});
 render(<ArtifactWorkspacePanel {...props}/>);
 fireEvent.click(screen.getByText("Artifact workspace"));
 fireEvent.click(screen.getByRole("button",{name:"Load workspaces"}));
 expect(await screen.findByRole("button",{name:"Collect / retry repository files"})).toBeDisabled();
});
