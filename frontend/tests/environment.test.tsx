import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { isAllowedRoute } from "@/shared/api/proxy";
import {
  ConfigurationFields,
  cleanConfiguration,
} from "@/modules/environment-management/components/configuration-fields";
import { allowedActions } from "@/modules/environment-management/model/policy";
import type {
  ConfigurationSchema,
  Environment,
} from "@/modules/environment-management/model/types";
import type { Identity } from "@/shared/auth/claims";
describe("Environment module", () => {
  it("allows all documented routes with exact methods", () => {
    const contract = JSON.parse(
      readFileSync(
        resolve(process.cwd(), "../docs/environment-openapi.json"),
        "utf8",
      ),
    ) as { paths: Record<string, Record<string, unknown>> };
    let count = 0;
    for (const [path, methods] of Object.entries(contract.paths))
      for (const method of Object.keys(methods)) {
        const parts = path
          .replace("/api/v1/", "")
          .replace("{environmentId}", "ENV-test")
          .replace("{distribution}", "AKS")
          .replace("{schemaVersion}", "1.0")
          .replace("{version}", "2")
          .split("/");
        expect(isAllowedRoute(method.toUpperCase(), parts)).toBe(true);
        count++;
      }
    expect(count).toBe(22);
    expect(isAllowedRoute("DELETE", ["environments", "ENV-test"])).toBe(false);
    expect(
      isAllowedRoute("POST", ["environments", "ENV-test", "versions"]),
    ).toBe(false);
    expect(
      isAllowedRoute("GET", [
        "environments",
        "configuration-schemas",
        "../../etc",
        "1.0",
      ]),
    ).toBe(false);
  });
  it.each(["aks", "gke", "oke", "eks"])(
    "renders provider-specific %s fields from the actual API schema",
    (dist) => {
      const schema = JSON.parse(
        readFileSync(
          resolve(
            process.cwd(),
            `../src/navigan/modules/environment_management/schemas/${dist}-1.0.json`,
          ),
          "utf8",
        ),
      ) as ConfigurationSchema;
      render(
        <ConfigurationFields schema={schema} value={{}} onChange={vi.fn()} />,
      );
      const label = {
        aks: "Tenant ID",
        gke: "Project ID",
        oke: "Tenancy OCID",
        eks: "Account ID",
      }[dist]!;
      expect(screen.getByLabelText(new RegExp(label))).toBeInTheDocument();
    },
  );
  it("preserves unknown fields and boolean false while removing empty draft inputs", () => {
    expect(
      cleanConfiguration({
        extensions: { feature: false },
        location: { region: "" },
        network: { subnets: [] },
      }),
    ).toEqual({ extensions: { feature: false } });
  });
  it("adds approved subnet entries", () => {
    const change = vi.fn();
    render(
      <ConfigurationFields
        schema={{
          type: "array",
          title: "Node subnets",
          items: { type: "string" },
        }}
        value={[]}
        onChange={change}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add node subnets" }));
    expect(change).toHaveBeenCalledWith([""]);
  });
  it("restricts approval affordances to architects", () => {
    const env = { status: "UNDER_REVIEW" } as Environment;
    expect(
      allowedActions(env, { roles: ["CLOUD_ENGINEER"] } as Identity),
    ).toEqual([]);
    expect(
      allowedActions(env, { roles: ["PLATFORM_ARCHITECT"] } as Identity),
    ).toEqual(["approve", "reject"]);
  });
});
