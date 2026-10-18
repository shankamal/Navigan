import { describe, expect, it } from "vitest";
import {
  validateSourceConnection,
  type SourceConnectionFields,
} from "@/modules/migration-management/source-connection-validation";
const fields: SourceConnectionFields = {
  name: "Payments migration",
  customer: "CUS-demo",
  mode: "REGISTER",
  registered: false,
  sourceId: "",
  clusterName: "payments-source",
  platform: "SELF_MANAGED",
  distribution: "Kubernetes (kubeadm)",
  location: "CLOUD",
  provider: "AWS",
  region: "ap-south-1",
  delivery: "AWS_SSM",
  account: "123456789012",
  instance: "i-0123456789abcdef0",
  role: "",
  kubeconfig: "/etc/kubernetes/admin.conf",
};
describe("source connection action validation", () => {
  it("validates all mandatory registration fields before saving", () => {
    const errors = validateSourceConnection(
      {
        ...fields,
        name: "",
        customer: "",
        clusterName: "",
        region: "",
        account: "",
        instance: "",
        kubeconfig: "",
      },
      "save",
    );
    expect(Object.keys(errors)).toEqual(
      expect.arrayContaining([
        "name",
        "customer",
        "clusterName",
        "region",
        "account",
        "instance",
        "kubeconfig",
      ]),
    );
  });
  it("rejects malformed AWS inputs and optional role when supplied", () => {
    expect(
      validateSourceConnection(
        {
          ...fields,
          account: "12345",
          region: "Mumbai",
          instance: "random",
          role: "not-an-arn",
          kubeconfig: "./admin.conf",
        },
        "save",
      ),
    ).toMatchObject({
      account: expect.any(String),
      region: expect.any(String),
      instance: expect.any(String),
      role: expect.any(String),
      kubeconfig: expect.any(String),
    });
  });
  it("does not require AWS-only details for on-premises Helm delivery", () => {
    expect(
      validateSourceConnection(
        {
          ...fields,
          location: "ON_PREMISES",
          provider: "",
          region: "Chennai DC1",
          delivery: "MANUAL_HELM",
          account: "",
          instance: "",
          kubeconfig: "",
        },
        "save",
      ),
    ).toEqual({});
  });
  it("requires a saved source before verification", () => {
    expect(validateSourceConnection(fields, "verify").sourceId).toBeDefined();
    expect(
      validateSourceConnection(
        { ...fields, registered: true, sourceId: "SRC-demo" },
        "verify",
      ),
    ).toEqual({});
  });
  it("blocks continuing with a missing or stale connection verification", () => {
    const ready = { ...fields, registered: true, sourceId: "SRC-demo" };
    const now = Date.parse("2026-10-18T17:00:00Z");
    expect(
      validateSourceConnection(ready, "continue", "", now).connection,
    ).toBeDefined();
    expect(
      validateSourceConnection(ready, "continue", "2026-10-18T16:57:59Z", now)
        .connection,
    ).toBeDefined();
    expect(
      validateSourceConnection(ready, "continue", "2026-10-18T16:59:45Z", now),
    ).toEqual({});
  });
});
