// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import { forwardRequest, isAllowedRoute } from "@/shared/api/proxy";

const migration = `MIG-${"a".repeat(32)}`;
const workspace = `AWS-${"b".repeat(32)}`;
const base = ["migrations", migration, "artifact-workspaces"];
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it.each([
  ["GET", base],
  ["POST", base],
  ["GET", [...base, workspace]],
  ["POST", [...base, workspace, "collection-jobs"]],
  ["POST", [...base, workspace, "exports"]],
])("permits the workspace endpoint %s %j", (method, path) => {
  expect(isAllowedRoute(method as string, path as string[])).toBe(true);
});

it.each([
  ["PUT", base],
  ["DELETE", base],
  ["POST", [...base, workspace]],
  ["GET", [...base, workspace, "collection-jobs"]],
  ["GET", [...base, workspace, "exports"]],
  ["POST", [...base, workspace, "exports", "extra"]],
  ["POST", [...base, "AWS-invalid", "collection-jobs"]],
  ["GET", [...base, "../secrets"]],
  ["GET", [...base, workspace, "unknown"]],
  ["POST", [...base, workspace, "collection-jobs", "extra"]],
  ["POST", ["migrations", "MIG-invalid", "artifact-workspaces"]],
])("rejects unsupported workspace request %s %j", (method, path) => {
  expect(isAllowedRoute(method as string, path as string[])).toBe(false);
});

it("forwards workspace creation to AWS with the body and required headers", async () => {
  vi.stubEnv(
    "NAVIGAN_API_ORIGIN",
    "https://example.execute-api.ap-south-1.amazonaws.com",
  );
  vi.stubEnv("NAVIGAN_API_BASE_PATH", "/v1/api/v1");
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      Response.json({ workspaceId: workspace }, { status: 201 }),
    );
  vi.stubGlobal("fetch", fetcher);
  const body = JSON.stringify({
    version: 2,
    inventoryDigest: "snapshot",
    namespaces: ["retailflow"],
  });
  const response = await forwardRequest(
    new Request("http://localhost:3000/api/platform/" + base.join("/"), {
      method: "POST",
      headers: {
        authorization: "Bearer test.token",
        "content-type": "application/json",
        "if-match": "2",
        "idempotency-key": "workspace-test",
      },
      body,
    }),
    base,
  );
  expect(response.status).toBe(201);
  expect(await response.json()).toEqual({ workspaceId: workspace });
  expect(fetcher.mock.calls[0][0].href).toBe(
    "https://example.execute-api.ap-south-1.amazonaws.com/v1/api/v1/" +
      base.join("/"),
  );
  const forwarded = fetcher.mock.calls[0][1];
  expect(forwarded.method).toBe("POST");
  expect(forwarded.body).toBe(body);
  expect(forwarded.headers.get("Authorization")).toBe("Bearer test.token");
  expect(forwarded.headers.get("If-Match")).toBe("2");
  expect(forwarded.headers.get("Idempotency-Key")).toBe("workspace-test");
});

it("still rejects unauthenticated workspace requests before forwarding", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const response = await forwardRequest(
    new Request("http://localhost:3000/api/platform/" + base.join("/")),
    base,
  );
  expect(response.status).toBe(401);
  expect(fetcher).not.toHaveBeenCalled();
});
