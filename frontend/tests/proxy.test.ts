// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import {
  forwardRequest,
  isAllowedRoute,
  upstreamUrl,
} from "@/shared/api/proxy";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("Same-origin API proxy", () => {
  it("allows exactly the 18 documented routes", () => {
    const contract = JSON.parse(
      readFileSync(new URL("../../docs/openapi.json", import.meta.url), "utf8"),
    ) as { paths: Record<string, Record<string, unknown>> };
    let count = 0;
    for (const [path, methods] of Object.entries(contract.paths))
      for (const method of Object.keys(methods)) {
        const segments = path
          .replace("/api/v1/", "")
          .replace("{customerId}", "CUS-test-123")
          .split("/");
        expect(isAllowedRoute(method.toUpperCase(), segments)).toBe(true);
        count++;
      }
    expect(count).toBe(18);
    expect(isAllowedRoute("DELETE", ["customers", "CUS-test-123"])).toBe(false);
    expect(
      isAllowedRoute("GET", ["customers", "CUS-test-123", "../secrets"]),
    ).toBe(false);
    expect(
      isAllowedRoute("POST", ["customers", "CUS-test-123", "audit-log"]),
    ).toBe(false);
  });
  it("uses the supplied API host and explicit SAM stage", () => {
    expect(upstreamUrl(["customers", "CUS-test-123"], "?page=0").href).toBe(
      "https://q0i8bcekw1.execute-api.ap-south-1.amazonaws.com/v1/api/v1/customers/CUS-test-123?page=0",
    );
  });
  it("rejects unauthenticated requests without contacting AWS", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect(
      (
        await forwardRequest(
          new Request("https://navigan.example/api/platform/customers"),
          ["customers"],
        )
      ).status,
    ).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("forwards bearer/version/idempotency headers and exposes ETag, without cookies", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response('{"version":5}', {
        status: 200,
        headers: { ETag: '"5"' },
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    const request = new Request(
      "https://navigan.example/api/platform/customers/CUS-test-123",
      {
        method: "PUT",
        headers: {
          authorization: "Bearer test.jwt.token",
          "content-type": "application/json",
          "if-match": "4",
          "idempotency-key": "stable-key",
          cookie: "private=do-not-forward",
        },
        body: '{"name":"Updated"}',
      },
    );
    const result = await forwardRequest(request, ["customers", "CUS-test-123"]);
    const options = fetcher.mock.calls[0][1] as RequestInit;
    expect((options.headers as Headers).get("If-Match")).toBe("4");
    expect((options.headers as Headers).get("Idempotency-Key")).toBe(
      "stable-key",
    );
    expect((options.headers as Headers).get("Authorization")).toBe(
      "Bearer test.jwt.token",
    );
    expect((options.headers as Headers).get("cookie")).toBeNull();
    expect(options.redirect).toBe("manual");
    expect(result.headers.get("etag")).toBe('"5"');
    expect(result.headers.get("cache-control")).toBe("no-store");
  });
  it("blocks redirects and oversized bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(null, {
          status: 302,
          headers: { Location: "https://other.example" },
        }),
      ),
    );
    const get = new Request("https://navigan.example/api/platform/customers", {
      headers: { authorization: "Bearer token" },
    });
    expect((await forwardRequest(get, ["customers"])).status).toBe(502);
    const post = new Request(get.url, {
      method: "POST",
      headers: {
        authorization: "Bearer token",
        "content-type": "application/json",
      },
      body: JSON.stringify({ name: "a".repeat(65536) }),
    });
    expect((await forwardRequest(post, ["customers"])).status).toBe(413);
  });
});
