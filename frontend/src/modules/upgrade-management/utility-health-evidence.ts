import type { z } from "zod";
import type { platformComponentInventorySchema } from "@/modules/cluster-management/model";

export function falcoHealthEvidence(
  inventory: z.infer<typeof platformComponentInventorySchema> | undefined,
  now: number,
) {
  const runtime = inventory?.runtimeInventory;
  const observed = Date.parse(runtime?.observedAt ?? "");
  const expires = Date.parse(runtime?.expiresAt ?? "");
  if (
    !runtime ||
    !["READY", "DEGRADED"].includes(runtime.status) ||
    !Number.isFinite(observed) ||
    !Number.isFinite(expires) ||
    observed > now + 60_000 ||
    now - observed > 300_000 ||
    expires <= now
  ) {
    return [
      "Fresh runtime evidence is unavailable. Check the Falco application in Argo CD for the resource that is still progressing.",
    ];
  }
  const daemonsets = runtime.resources.filter(
    (item) =>
      item.kind === "DaemonSet" &&
      item.namespace === "navigan-security" &&
      item.name.toLowerCase().includes("falco"),
  );
  const evidence = daemonsets.length
    ? daemonsets.map((item) =>
        item.desired === 0
          ? `${item.name}: no pods desired (0). Check node selection and cluster scaling; readiness has not been established.`
          : `${item.name}: ${item.ready}/${item.desired} pods ready (${item.status}).`,
      )
    : [
        "No Falco DaemonSet was present in the reported runtime inventory. This is incomplete evidence, not proof that Falco is absent.",
      ];
  const warnings = runtime.warningEvents.filter(
    (item) =>
      item.namespace === "navigan-security" &&
      item.resourceName?.toLowerCase().includes("falco"),
  );
  return [
    ...evidence,
    ...warnings
      .slice(-3)
      .map(
        (item) =>
          `${item.reason}: ${item.message} · ${item.lastObservedAt ?? "Time not reported"}`,
      ),
  ];
}
