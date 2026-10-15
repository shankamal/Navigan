"""Read-only, evidence-backed per-workload migration assessment presentation."""
from .dependency_evidence import WORKLOAD_KINDS


def build_workload_assessment_report(draft, evaluations, dependency_evidence, target_id):
    selected = [
        r for r in (draft or {}).get("resources", [])
        if isinstance(r, dict) and not r.get("dependency") and r.get("kind") in WORKLOAD_KINDS
    ]
    evaluations = evaluations or []
    relationships = (dependency_evidence or {}).get("relationships") or []
    unresolved = (dependency_evidence or {}).get("unresolvedReferences") or []
    coverage = (dependency_evidence or {}).get("workloadCoverage") or {}
    rows = []
    for resource in selected:
        identity = {key: resource.get(key) for key in ("kind", "namespace", "name")}
        evaluation = next((e for e in evaluations if isinstance(e, dict)
            and all((e.get("resource") or {}).get(k) == resource.get(k)
                    for k in ("apiVersion", "kind", "namespace", "name"))), None)
        matched = lambda e: all((e.get("source") or {}).get(k) == identity[k]
                                for k in identity)
        dependencies = [e["target"] for e in relationships if matched(e)]
        missing = [e["target"] for e in unresolved if matched(e)]
        checks = (evaluation or {}).get("checks") or []
        rows.append({
            "source": {**identity, "apiVersion": resource.get("apiVersion")},
            "targetClusterId": target_id,
            "plannedTreatment": resource.get("treatment"),
            "compatibilityStatus": (evaluation or {}).get("status", "PENDING_EVIDENCE"),
            "observedDependencies": dependencies,
            "unresolvedDependencies": missing,
            "dependencyEvidenceStatus": "PARTIAL" if dependencies or missing else "NOT_VERIFIED",
            "checks": [{
                "capability": check.get("capability"),
                "status": check.get("status"),
                "reason": check.get("reason"),
                "nextAction": check.get("nextAction"),
            } for check in checks if isinstance(check, dict)],
        })
    return {
        "status": "ASSESSMENT_ONLY",
        "executionReady": False,
        "targetClusterId": target_id,
        "workloadCount": len(rows),
        "dependencyCoverage": coverage,
        "workloads": rows,
        "limitations": [
            "Missing dependency relationships are not evidence of no dependencies.",
            "Pending target capability evidence prevents execution approval.",
            "This report neither deploys workloads nor generates migration artifacts.",
        ],
    }
