
"""Read-only identity dependency evidence, never authorization proof."""

WORKLOADS = {
    "Deployment", "StatefulSet", "DaemonSet",
    "Pod", "Job", "CronJob",
}


def evaluate_identity_dependencies(
        resource, resources, planned, snapshot, *,
        target_current=False):

    if not isinstance(resource, dict):
        return []

    if resource.get("kind") not in WORKLOADS:
        return []

    pod = resource.get("pod")

    if not isinstance(pod, dict):
        return []

    namespace = resource.get("namespace")
    account = pod.get("serviceAccountName")
    references = set()

    if isinstance(account, str) and account and account != "default":
        references.add(("ServiceAccount", account))

    for ref in resource.get("dependencyReferences") or []:
        if (
            isinstance(ref, dict)
            and ref.get("kind") in {"ServiceAccount", "Secret"}
            and isinstance(ref.get("name"), str)
            and ref["name"]
        ):
            references.add((ref["kind"], ref["name"]))

    def identity(r):
        return (r.get("kind"), r.get("name"))

    observed = {
        identity(r) for r in resources
        if isinstance(r, dict)
        and r.get("namespace") == namespace
    }

    selected = {
        identity(r) for r in planned
        if isinstance(r, dict)
        and r.get("namespace") == namespace
        and r.get("treatment") in {"MIGRATE", "RECREATE"}
    }

    checks = []

    if references:
        included = sorted(references & observed & selected)
        missing = sorted(references - observed)
        outside = sorted((references & observed) - selected)

        def describe(label, items):
            if not items:
                return ""
            return label + ": " + ", ".join(
                f"{kind}/{name}" for kind, name in items[:10]
            ) + "."

        reason = " ".join(filter(None, [
            describe("Planned identity dependencies", included),
            describe("Not observed in source inventory", missing),
            describe("Not included in migration scope", outside),
            "Effective authorization and secret material remain unverified.",
        ]))

        checks.append({
            "capability": "Identity dependency scope",
            "status": (
                "PENDING_EVIDENCE" if missing or outside
                else "PARTIAL"
            ),
            "reason": reason,
            "nextAction": (
                "Resolve identity dependencies and securely recreate "
                "required credentials; validate effective permissions."
            ),
        })

    if not isinstance(account, str) or not account:
        return checks

    if not isinstance(namespace, str) or not namespace:
        return checks

    snapshot = snapshot if isinstance(snapshot, dict) else {}
    discovery = snapshot.get("supplementaryDiscovery") or {}
    inventory = snapshot.get("supplementaryInventory") or {}

    available = (
        target_current
        and discovery.get("ServiceAccount") == "AVAILABLE"
        and isinstance(inventory.get("ServiceAccount"), list)
    )

    if not available:
        status = "PENDING_EVIDENCE"
        reason = (
            "Fresh target ServiceAccount inventory is unavailable."
        )
    else:
        present = any(
            isinstance(r, dict)
            and r.get("namespace") == namespace
            and r.get("name") == account
            for r in inventory["ServiceAccount"]
        )

        if present:
            status = "PARTIAL"
            reason = (
                f"ServiceAccount {namespace}/{account} was observed "
                "in the same-named target namespace. RBAC, workload "
                "identity and registry authorization remain unverified."
            )
        else:
            status = "PENDING_EVIDENCE"
            reason = (
                f"ServiceAccount {namespace}/{account} was not observed "
                "in the returned target inventory. Confirm the target "
                "namespace and recreation plan."
            )

    checks.append({
        "capability": "Target ServiceAccount evidence",
        "status": status,
        "reason": reason,
        "nextAction": (
            "Confirm target namespace, ServiceAccount mapping, "
            "effective RBAC and image-pull authorization."
        ),
    })

    return checks
