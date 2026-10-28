"""Read-only, evidence-conservative source/target discovery coverage report.

This report never triggers collection, changes a migration, or treats an observed
resource as proof that a migration capability is compatible.
"""
from datetime import datetime, timezone

from .dependency_evidence import discover_dependencies

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}


def _freshness(observed_at, expires_at, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(observed_at, str) or not isinstance(expires_at, str):
        return "UNKNOWN"
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return "UNKNOWN"
    if observed.tzinfo is None or expires.tzinfo is None or observed > now or expires <= observed:
        return "UNKNOWN"
    return "CURRENT" if expires > now else "STALE"


def _capability(status, reason):
    return {"status": status, "reason": reason}


def build_discovery_coverage(source_inventory, planning_draft, target_assessment, now=None):
    source_inventory = source_inventory or {}
    planning_draft = planning_draft or {}
    target_assessment = target_assessment or {}
    resources = source_inventory.get("resources") or []
    selected_items = [
        item for item in planning_draft.get("resources") or []
        if isinstance(item, dict) and not item.get("dependency")
        and item.get("kind") in WORKLOAD_KINDS
    ]
    selected = {
        (item.get("apiVersion"), item.get("kind"), item.get("namespace"), item.get("name"))
        for item in selected_items
    }
    deps = discover_dependencies(resources, selected)
    evidence = deps["workloadCoverage"]
    expected = len(selected)
    selected_observed = evidence["selectedWorkloads"]
    source_capabilities = {
        "inventory": _capability(
            "PARTIAL" if resources else "MISSING",
            "Saved inventory exists; full source-estate and permission coverage are not certified."
            if resources else "No source inventory is available.",
        ),
        "dependencies": _capability(
            "PARTIAL" if selected_observed == expected and evidence["withReferenceEvidence"] else "MISSING",
            f"{evidence['withReferenceEvidence']}/{expected} selected workloads have dependency-reference evidence; "
            f"{evidence['withoutReferenceEvidence']} observed workloads lack references. "
            "References do not prove external/network dependencies are complete.",
        ),
        "storage": _capability("MISSING", "PVC ownership, volume data and migration strategy have not been verified."),
        "networking": _capability("MISSING", "Ingress, DNS, traffic flow and network policy compatibility have not been verified."),
        "identity": _capability("MISSING", "RBAC, secrets and service identity migration compatibility have not been verified."),
        "operators": _capability("MISSING", "CRDs, operators and admission compatibility have not been verified."),
    }
    source_freshness = _freshness(
        source_inventory.get("observedAt"),
        source_inventory.get("expiresAt") or source_inventory.get("inventoryExpiresAt"),
        now,
    )

    snapshot = target_assessment.get("snapshot") or {}
    target_freshness = _freshness(
        snapshot.get("observedAt"),
        snapshot.get("inventoryExpiresAt") or snapshot.get("expiresAt"),
        now,
    )
    target_capabilities = {}
    for key in ("kubernetesApi", "compute", "storage", "networking", "identity", "dependencies"):
        evidence_item = (snapshot.get("capabilityEvidence") or {}).get(key) or {}
        status = evidence_item.get("status")
        if target_freshness == "STALE":
            status = "STALE"
        elif status not in {"PARTIAL", "NOT_VERIFIED"}:
            status = "MISSING"
        elif status == "NOT_VERIFIED":
            status = "MISSING"
        target_capabilities[key] = _capability(
            status, evidence_item.get("reason") or "No verified target capability evidence."
        )
    # The target snapshot explicitly lacks complete coverage until independently accepted.
    return {
        "source": {
            "inventoryResourceCount": len(resources),
            "selectedWorkloadCount": expected,
            "matchedSelectedWorkloads": selected_observed,
            "dependencyEvidence": deps,
            "freshness": source_freshness,
            "capabilities": source_capabilities,
            "discoveryAccepted": False,
        },
        "target": {
            "inventoryResourceCount": snapshot.get("resourceCount"),
            "freshness": target_freshness,
            "capabilities": target_capabilities,
            "discoveryAccepted": False,
        },
        "note": "Evidence inventory alone cannot certify 100% source or target discovery.",
    }
