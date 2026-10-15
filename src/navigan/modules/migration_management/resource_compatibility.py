"""Conservative, actionable compatibility results for every selected resource.

These are observations and requirements, never automatic migration approval.
"""


def evaluate_selected_resources(resources, planned, source_findings, api, storage,
                                scheduling, *, target_current=False):
    by_key = {
        (r.get("apiVersion"), r.get("kind"), r.get("namespace"), r.get("name")): r
        for r in resources if isinstance(r, dict)
    }
    api_by_key = {
        (r.get("apiVersion"), r.get("kind"), r.get("namespace"), r.get("name")): r
        for r in api
    }
    storage_by_key = {
        (r.get("apiVersion"), r.get("kind"), r.get("namespace"), r.get("name")): r
        for r in storage
    }
    scheduling_by_key = {
        (r.get("apiVersion"), r.get("kind"), r.get("namespace"), r.get("name")): r
        for r in scheduling
    }
    checks = []
    for item in planned:
        if not isinstance(item, dict):
            continue
        key = (item.get("apiVersion"), item.get("kind"),
               item.get("namespace"), item.get("name"))
        resource = by_key.get(key)
        if item.get("treatment") == "RETIRE":
            checks.append({"resource": dict(zip(("apiVersion", "kind", "namespace", "name"), key)),
                           "status": "REMEDIATION_REQUIRED",
                           "checks": [{"capability": "Resource treatment", "status": "REMEDIATION_REQUIRED",
                                       "reason": "The resource is marked for retirement, not target migration.",
                                       "nextAction": "Confirm the retirement and its dependent workloads before proceeding."}]})
            continue
        results = []
        def add(capability, status, reason, action):
            results.append({"capability": capability, "status": status,
                            "reason": reason, "nextAction": action})
        if resource is None:
            add("Source inventory", "PENDING_EVIDENCE",
                "Selected resource was not found in the current source inventory.",
                "Rediscover the source and reselect the resource from the current assessment.")
        for finding in source_findings:
            if not isinstance(finding, dict):
                continue
            if (finding.get("resourceKind"), finding.get("namespace"), finding.get("resourceName")) != (key[1], key[2], key[3]):
                continue
            blocker = finding.get("severity") == "BLOCKER" or finding.get("disposition") == "BLOCKER"
            add("Source assessment", "INCOMPATIBLE" if blocker else "REMEDIATION_REQUIRED",
                finding.get("message") or "Source assessment finding requires review.",
                finding.get("remediation") or "Resolve the recorded source assessment finding and reassess.")
        api_result = api_by_key.get(key)
        add("Kubernetes API", api_result.get("status") if api_result else "PENDING_EVIDENCE",
            api_result.get("reason") if api_result else "No resource-bound target API discovery result was returned.",
            "Collect fresh target API group/version/kind and admission evidence; confirm this resource is served.")
        if key[1] == "PersistentVolumeClaim":
            observed = storage_by_key.get(key)
            add("Persistent storage", observed.get("status") if observed else "PENDING_EVIDENCE",
                observed.get("reason") if observed else "StorageClass, CSI and volume migration compatibility have not been established.",
                "Verify target StorageClass, CSI driver, access modes, capacity, topology and data-transfer method.")
        if key[1] in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}:
            observed = scheduling_by_key.get(key)
            add("Workload scheduling", observed.get("status") if observed else "PENDING_EVIDENCE",
                observed.get("reason") if observed else "Scheduling evidence is missing for the selected workload.",
                "Verify source resource requests and target node headroom, selectors, taints, quotas and affinity.")
        # Apply evidence checks only where the Kubernetes kind requires them.
        kind = key[1]
        if kind in {"Service", "Ingress", "NetworkPolicy"}:
            add("Networking", "PENDING_EVIDENCE",
                "Destination network routing or policy enforcement is not verified.",
                "Verify destination ingress, service routing or policy support for this resource.")
        if kind in {"ServiceAccount", "Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding", "Secret",
                    "Deployment", "StatefulSet", "DaemonSet", "Pod", "Job", "CronJob"}:
            add("Identity and secrets", "PENDING_EVIDENCE",
                "Target identity, authorization or referenced secret/image access is not verified.",
                "Verify required service account, RBAC, registry and secret access on the destination.")
        if kind in {"CustomResourceDefinition", "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"}:
            add("Controllers and dependencies", "PENDING_EVIDENCE",
                "Target API extension or admission controller is not verified.",
                "Discover the matching target CRD or webhook and check its admission behavior.")
        if kind == "StatefulSet":
            add("Stateful storage dependencies", "PENDING_EVIDENCE",
                "Volume templates and persistence dependencies remain unverified.",
                "Verify target PVC mappings, CSI provisioning and data migration strategy.")
        if not target_current:
            add("Evidence freshness", "PENDING_EVIDENCE",
                "Target evidence is missing, expired or not bound to a current inventory.",
                "Refresh the target inventory and repeat compatibility assessment.")
        statuses = {entry["status"] for entry in results}
        status = ("INCOMPATIBLE" if "INCOMPATIBLE" in statuses else
                  "REMEDIATION_REQUIRED" if "REMEDIATION_REQUIRED" in statuses else
                  "PENDING_EVIDENCE" if "PENDING_EVIDENCE" in statuses or "PARTIAL" in statuses else
                  "COMPATIBLE")
        source_checks = [c for c in results if c["capability"] in {"Source assessment", "Source inventory", "Resource treatment"}]
        target_checks = [c for c in results if c not in source_checks]
        source_status = ("INCOMPATIBLE" if any(c["status"] == "INCOMPATIBLE" for c in source_checks) else
                         "REMEDIATION_REQUIRED" if any(c["status"] == "REMEDIATION_REQUIRED" for c in source_checks) else
                         "PENDING_EVIDENCE" if source_checks else "NO_FINDINGS")
        target_status = ("INCOMPATIBLE" if any(c["status"] == "INCOMPATIBLE" for c in target_checks) else
                         "PENDING_EVIDENCE" if any(c["status"] in {"PENDING_EVIDENCE", "PARTIAL"} for c in target_checks) else
                         "COMPATIBLE" if target_checks and all(c["status"] == "COMPATIBLE" for c in target_checks) else
                         "NOT_EVALUATED")
        checks.append({"resource": dict(zip(("apiVersion", "kind", "namespace", "name"), key)),
                       "status": status, "sourceStatus": source_status, "targetStatus": target_status, "checks": results})
    return checks
