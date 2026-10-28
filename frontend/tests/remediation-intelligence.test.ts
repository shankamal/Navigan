import { describe, it, expect } from "vitest";
import type { Assessment } from "@/modules/migration-management/model";
import {
  analyzeRemediationFinding,
  recommendFinding,
} from "@/modules/migration-management/planning-recommendations";

const assessment = (code: string, message: string, category = "Other") =>
  ({
    findings: [
      {
        code,
        message,
        category,
        severity: "WARNING",
        resourceName: "retailflow-api",
      },
    ],
  }) as Assessment;

describe("explainable remediation intelligence", () => {
  it.each([
    [
      "IMAGE_DIGEST",
      "Container image is not pinned to an immutable digest",
      "RECONFIGURE",
    ],
    [
      "NAMED_SERVICE_ACCOUNT",
      "Workload uses a named Kubernetes service account",
      "RECONFIGURE",
    ],
    [
      "NETWORK_POLICY",
      "NetworkPolicy enforcement requires target validation",
      "RECONFIGURE",
    ],
    ["DEPRECATED_API", "Uses a deprecated API version", "REPLACE"],
    ["STORAGE_MAPPING", "Persistent volume mapping requires review", "REVIEW"],
    ["CPU_MEMORY", "Container CPU or memory requests are missing", "REVIEW"],
    [
      "CONFIG_REF",
      "Workload references Secrets or ConfigMaps whose contents were intentionally excluded",
      "REVIEW",
    ],
    ["TARGET_UNVERIFIED", "StorageClass gp3 is not verified", "REVIEW"],
    ["UNKNOWN_FINDING", "Unsupported operational hypothesis", "REVIEW"],
  ])("%s selects safe treatment %s", (code, message, expected) => {
    const result = analyzeRemediationFinding(assessment(code, message), 0);
    expect(result?.treatment).toBe(expected);
    expect(result?.requiresHumanReview).toBe(true);
    expect(result?.verificationRequirements.length).toBeGreaterThan(0);
    expect(
      recommendFinding(assessment(code, message), 0)?.evidenceReference,
    ).toBe("");
  });
  it("never treats a target platform label as verified capability", () => {
    const result = analyzeRemediationFinding(
      assessment("STORAGE_MAPPING", "PVC storage compatibility"),
      0,
      "EKS",
    );
    expect(result?.treatment).toBe("REVIEW");
    expect(result?.targetMapping).toContain("do not assume it exists");
    expect(result?.targetMapping).toContain("Evidence required:");
  });
  it("does not invent a remediation for missing findings", () => {
    expect(analyzeRemediationFinding(assessment("A", "B"), 3)).toBeNull();
    expect(recommendFinding(assessment("A", "B"), 3)).toBeNull();
  });
});
