import { afterEach, describe, expect, it, vi } from "vitest";
import { isSourceFirstEnabled } from "@/modules/migration-management/source-first-config";

afterEach(() => vi.unstubAllEnvs());

describe("source-first release switch", () => {
  it.each([
    ["production", "true", true],
    ["production", "false", false],
    ["production", undefined, false],
    ["production", "TRUE", false],
    ["production", "1", false],
    ["development", undefined, true],
    ["development", "false", false],
    ["development", "true", true],
    ["test", undefined, false],
  ] as const)("NODE_ENV=%s, configured=%s -> %s", (mode, flag, expected) => {
    vi.stubEnv("NODE_ENV", mode);
    vi.stubEnv("MIGRATION_SOURCE_FIRST_ENABLED", flag);
    expect(isSourceFirstEnabled()).toBe(expected);
  });

  it("never enables production through the UI preview setting", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MIGRATION_SOURCE_FIRST_ENABLED", undefined);
    vi.stubEnv("NEXT_PUBLIC_MIGRATION_UI_PREVIEW", "true");
    expect(isSourceFirstEnabled()).toBe(false);
  });
});
