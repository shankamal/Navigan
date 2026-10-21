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
  expect(await screen.findByText(/0 planned artifacts/)).toHaveTextContent(
    "Files and images not collected",
  );
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
