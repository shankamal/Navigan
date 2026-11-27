"""Source-observed network dependency scope; not a target connectivity test."""

WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "Pod", "Job", "CronJob"}


def _service_names(resource, field):
    refs = resource.get(field)
    if not isinstance(refs, list):
        return None
    if any(not isinstance(ref, dict) or not isinstance(ref.get("kind"), str)
           or not isinstance(ref.get("name"), str) or not ref["name"] for ref in refs):
        return None
    return sorted({ref["name"] for ref in refs if ref["kind"] == "Service"})


def network_scope_evidence(resource, planned, resources):
    """Check explicit same-namespace Service references against saved scope.

    Missing selection is not proof of missing target Service. Empty references
    are not proof that a workload has no network dependencies. No target
    traffic, ports, policies, DNS or controller compatibility is inferred.
    """
    if not isinstance(resource, dict):
        return None
    kind = resource.get("kind")
    if kind not in WORKLOADS | {"Ingress"}:
        return None
    field = "backendServiceReferences" if kind == "Ingress" else "dependencyReferences"
    names = _service_names(resource, field)
    noun = "Ingress backend" if kind == "Ingress" else "Workload-to-Service"
    if names is None:
        return {"status": "PENDING_EVIDENCE", "reason": f"{noun} references were not fully captured.",
                "nextAction": "Review source manifest references before validating target connectivity."}
    if not names:
        return {"status": "PENDING_EVIDENCE", "reason": f"No explicit {noun} Service references were reported; this does not establish that network dependencies are absent.",
                "nextAction": "Review rendered manifests and external dependencies."}
    namespace = resource.get("namespace")
    source_names = {r.get("name") for r in resources if isinstance(r, dict)
                    and r.get("kind") == "Service" and r.get("namespace") == namespace}
    selected_names = {r.get("name") for r in planned if isinstance(r, dict)
                      and r.get("kind") == "Service" and r.get("namespace") == namespace
                      and r.get("treatment") == "MIGRATE"}
    absent = [name for name in names if name not in source_names]
    outside = [name for name in names if name in source_names and name not in selected_names]
    included = [name for name in names if name in source_names and name in selected_names]
    # Bound display size; retain full counts and deterministic ordering.
    def describe(label, values):
        if not values:
            return ""
        return f"{label} ({len(values)}): " + ", ".join(values[:10]) + (", …" if len(values) > 10 else "") + "."
    reason = " ".join(part for part in (
        describe("Selected source Services", included),
        describe("Services not observed in source inventory", absent),
        describe("Observed Services not marked MIGRATE", outside),
        "Target routing, DNS, policy enforcement and external dependencies remain unverified.",
    ) if part)
    return {"status": "PENDING_EVIDENCE" if absent or outside else "PARTIAL",
            "reason": reason,
            "nextAction": "Resolve missing or unselected Service references with an explicit target mapping or scope decision; then validate target routing."
            if absent or outside else "Validate rendered Service selectors, backend ports, DNS, ingress and policy behavior on the target."}
