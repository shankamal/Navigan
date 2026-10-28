import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  parsePublicConfig,
  publicConfigFromEnvironment,
} from "@/shared/config/public-config";

const environment = (name: string) => ({
  NAVIGAN_PUBLIC_OIDC_AUTHORITY: `https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_${name}Pool`,
  NAVIGAN_PUBLIC_OIDC_CLIENT_ID: `${name}client`,
  NAVIGAN_PUBLIC_APP_URL: `https://${name}.example.invalid`,
  DB_PASSWORD: "must-never-be-public",
  AWS_SECRET_ACCESS_KEY: "must-never-be-public",
  NAVIGAN_API_ORIGIN: "https://private-upstream.example.invalid",
});

describe("runtime public configuration", () => {
  afterEach(() => vi.unstubAllGlobals());
  beforeEach(() => vi.resetModules());

  it("evaluates two environment configurations from identical code without rebuilding", () => {
    const dev = publicConfigFromEnvironment(environment("dev"));
    const prod = publicConfigFromEnvironment(environment("prod"));
    expect(dev.oidcClientId).toBe("devclient");
    expect(prod.oidcClientId).toBe("prodclient");
    expect(dev.appUrl).toBe("https://dev.example.invalid");
    expect(prod.appUrl).toBe("https://prod.example.invalid");
    expect(JSON.stringify([dev, prod])).not.toContain("must-never-be-public");
    expect(JSON.stringify(dev)).not.toContain("private-upstream");
  });

  it("supports existing runtime NEXT_PUBLIC variables without baking them into clients", () => {
    const legacy = publicConfigFromEnvironment({
      NEXT_PUBLIC_OIDC_AUTHORITY:
        environment("dev").NAVIGAN_PUBLIC_OIDC_AUTHORITY,
      NEXT_PUBLIC_OIDC_CLIENT_ID: "devclient",
      NEXT_PUBLIC_APP_URL: "http://localhost:3000",
    });
    expect(legacy.oidcClientId).toBe("devclient");
  });

  it("uses explicit new settings ahead of legacy runtime variables", () => {
    expect(
      publicConfigFromEnvironment({
        ...environment("dev"),
        NEXT_PUBLIC_OIDC_CLIENT_ID: "oldclient",
      }).oidcClientId,
    ).toBe("devclient");
  });

  it("never enables the preview in production", () => {
    expect(
      publicConfigFromEnvironment({
        ...environment("dev"),
        NODE_ENV: "production",
        NAVIGAN_PUBLIC_MIGRATION_UI_PREVIEW: "true",
      }).migrationUiPreview,
    ).toBe(false);
  });

  it.each([
    { oidcAuthority: "https://attacker.example.invalid/pool" },
    { oidcClientId: "" },
    { appUrl: "http://public.example.invalid" },
    { appUrl: "https://user:password@example.invalid" },
    { appUrl: "https://example.invalid/path" },
    { corporateLogoUrl: "javascript:alert(1)" },
    { migrationConnectorImageDigest: "latest" },
    { DB_PASSWORD: "not-allowed" },
  ])("rejects malformed or extra public values %j", (change) => {
    expect(() =>
      parsePublicConfig({
        ...publicConfigFromEnvironment(environment("dev")),
        ...change,
      }),
    ).toThrow();
  });

  it("coalesces bootstrap requests and exposes the selected identity only afterward", async () => {
    const module = await import("@/shared/config/runtime-config");
    let respond!: (value: Response) => void;
    const fetcher = vi.fn().mockReturnValue(
      new Promise<Response>((resolve) => {
        respond = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    const first = module.loadRuntimeConfig();
    const second = module.loadRuntimeConfig();
    expect(module.authConfigured).toBe(false);
    respond(Response.json(publicConfigFromEnvironment(environment("dev"))));
    await Promise.all([first, second]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(module.authConfigured).toBe(true);
    expect(module.runtimeConfig().oidcClientId).toBe("devclient");
  });

  it("allows a retry after a failed bootstrap without inventing identity defaults", async () => {
    const module = await import("@/shared/config/runtime-config");
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response("unavailable", { status: 503 }))
      .mockResolvedValueOnce(
        Response.json(publicConfigFromEnvironment(environment("dev"))),
      );
    vi.stubGlobal("fetch", fetcher);
    await expect(module.loadRuntimeConfig()).rejects.toThrow();
    expect(module.authConfigured).toBe(false);
    await module.loadRuntimeConfig();
    expect(module.authConfigured).toBe(true);
  });
});
