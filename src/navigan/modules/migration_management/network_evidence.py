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
                      and r.get("treatment") in {"MIGRATE", "RECREATE"}}
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
        describe("Observed Services not planned for migration or recreation", outside),
        "Target routing, DNS, policy enforcement and external dependencies remain unverified.",
    ) if part)
    return {"status": "PENDING_EVIDENCE" if absent or outside else "PARTIAL",
            "reason": reason,
            "nextAction": "Resolve missing or unselected Service references with an explicit target mapping or scope decision; then validate target routing."
            if absent or outside else "Validate rendered Service selectors, backend ports, DNS, ingress and policy behavior on the target."}


NETWORK_KINDS = {"Service", "Ingress", "NetworkPolicy"}


def build_network_inventory(resources):
    """Retain observed network object identities, not configuration."""
    return [
        {
            "kind": r["kind"],
            "namespace": r["namespace"],
            "name": r["name"],
        }
        for r in resources
        if isinstance(r, dict)
        and r.get("kind") in NETWORK_KINDS
        and isinstance(r.get("namespace"), str)
        and r["namespace"]
        and isinstance(r.get("name"), str)
        and r["name"]
    ]


def evaluate_target_network(resource, snapshot, *,
                            target_current=False):
    """Compare observed names without claiming connectivity or ownership."""
    if not isinstance(resource, dict):
        return None

    kind = resource.get("kind")
    namespace = resource.get("namespace")

    if not isinstance(namespace, str) or not namespace:
        return None

    references = set()

    if kind in NETWORK_KINDS:
        name = resource.get("name")
        if isinstance(name, str) and name:
            references.add((kind, name))

    if kind in WORKLOADS or kind == "Ingress":
        field = (
            "backendServiceReferences"
            if kind == "Ingress"
            else "dependencyReferences"
        )

        names = _service_names(resource, field)

        if names:
            references.update(
                ("Service", name) for name in names
            )

    if not references:
        return None

    action = (
        "Confirm target namespace, resource ownership, Service selectors, "
        "backend ports, ingress controller, DNS and network policy behavior."
    )

    inventory = (
        snapshot.get("networkInventory")
        if isinstance(snapshot, dict)
        else None
    )

    if not target_current or not isinstance(inventory, list):
        return {
            "capability": "Target network object evidence",
            "status": "PENDING_EVIDENCE",
            "reason": "Fresh target network object inventory is unavailable.",
            "nextAction": action,
        }

    observed = {
        (r.get("kind"), r.get("name"))
        for r in inventory
        if isinstance(r, dict)
        and r.get("namespace") == namespace
        and isinstance(r.get("kind"), str)
        and isinstance(r.get("name"), str)
    }

    matches = sorted(references & observed)
    unknown = sorted(references - observed)

    def describe(label, entries):
        if not entries:
            return ""

        return (
            f"{label} ({len(entries)}): "
            + ", ".join(
                f"{kind}/{name}"
                for kind, name in entries[:10]
            )
            + (" ..." if len(entries) > 10 else "")
            + "."
        )

    reason = " ".join(filter(None, [
        describe(
            "Same-named target network objects observed",
            matches
        ),
        describe(
            "Network objects not observed in returned inventory",
            unknown
        ),
        "Absence from inventory does not establish nonexistence.",
        "Existing object ownership, configuration and connectivity "
        "remain unverified.",
    ]))

    return {
        "capability": "Target network object evidence",
        "status": (
            "PENDING_EVIDENCE" if unknown
            else "PARTIAL"
        ),
        "reason": reason,
        "nextAction": action,
    }
