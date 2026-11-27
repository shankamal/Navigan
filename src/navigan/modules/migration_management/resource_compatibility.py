"""Conservative, actionable compatibility results for every selected resource.

These are observations and requirements, never automatic migration approval.
"""


from .network_evidence import (
    network_scope_evidence,
    evaluate_target_network,
)
from .identity_evidence import evaluate_identity_dependencies

def evaluate_selected_resources(resources, planned, source_findings, api, storage,
                                scheduling, *, target_current=False, data_strategy=None, target_snapshot=None):
    data_separate = data_strategy == "DATA_MIGRATION_HANDLED_SEPARATELY"
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
                           "sourceStatus": "REMEDIATION_REQUIRED", "targetStatus": "NOT_EVALUATED",
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
            disposition = finding.get("disposition")
            blocker = finding.get("severity") == "BLOCKER" or disposition == "BLOCKER"
            if disposition == "SEAMLESS" and not blocker:
                continue  # Informational/compatible source findings must not require remediation.
            needs_change = disposition in {"MANUAL_CHANGE", "AUTOMATED_CHANGE"} or finding.get("severity") == "WARNING"
            add("Source assessment",
                "INCOMPATIBLE" if blocker else "REMEDIATION_REQUIRED" if needs_change else "PENDING_EVIDENCE",
                finding.get("message") or "Source assessment finding requires review.",
                finding.get("remediation") or "Review this source assessment finding and confirm its treatment.")
        api_result = api_by_key.get(key)
        add("Kubernetes API", api_result.get("status") if api_result else "PENDING_EVIDENCE",
            api_result.get("reason") if api_result else "No resource-bound target API discovery result was returned.",
            "Collect fresh target API group/version/kind and admission evidence; confirm this resource is served.")
        if key[1] == "PersistentVolumeClaim":
            observed = storage_by_key.get(key)
            add("Persistent storage", observed.get("status") if observed else "PENDING_EVIDENCE",
                observed.get("reason") if observed else "StorageClass, CSI and volume migration compatibility have not been established.",
                "Verify target StorageClass, CSI driver, access modes, capacity, topology, provisioning and mounting."
                if data_separate else
                "Verify target StorageClass, CSI driver, access modes, capacity, topology and data-transfer method.")
        if key[1] in {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod"}:
            observed = scheduling_by_key.get(key)
            add("Workload scheduling", observed.get("status") if observed else "PENDING_EVIDENCE",
                observed.get("reason") if observed else "Scheduling evidence is missing for the selected workload.",
                "Verify source resource requests and target node headroom, selectors, taints, quotas and affinity.")
        # Apply evidence checks only where the Kubernetes kind requires them.
        kind = key[1]
        network_scope = network_scope_evidence(resource, planned, resources)
        if network_scope is not None:
            add("Network dependency scope", network_scope["status"],
                network_scope["reason"], network_scope["nextAction"])
        if kind in {"Service", "Ingress", "NetworkPolicy"}:
            add("Networking", "PENDING_EVIDENCE",
                "Destination network routing or policy enforcement is not verified.",
                "Verify destination ingress, service routing or policy support for this resource.")
        if kind in {"Deployment", "StatefulSet", "DaemonSet", "Pod", "Job", "CronJob"}:
            pod = resource.get("pod") if isinstance(resource, dict) else None
            # An inventory record alone cannot prove its Service, Ingress,
            # NetworkPolicy or external network dependencies are portable.
            # Keep that distinction explicit rather than reporting compatibility.
            add("Workload networking dependencies", "PENDING_EVIDENCE",
                "Workload-to-Service, Ingress, NetworkPolicy and external traffic dependencies have not been verified.",
                "Map source network dependencies to the target, then validate routing, policy and connectivity.")
            if not isinstance(pod, dict) or not isinstance(pod.get("volumes"), list):
                add("Workload volume dependencies", "PENDING_EVIDENCE",
                    "Pod volume references are not fully captured; persistent storage dependencies cannot be ruled out.",
                    "Collect volume references and validate PVC, CSI and mount requirements."
                    if data_separate else
                    "Collect volume references and validate PVC, CSI, mount, backup and data transfer mappings.")
            elif pod["volumes"]:
                volume_types = {v.get("type") if isinstance(v, dict) and isinstance(v.get("type"), str) else "unknown"
                                for v in pod["volumes"]}
                # Built-in nonpersistent volumes do not need dynamic CSI provisioning.
                # Their manifest schema/admission and configuration references still need validation.
                config_types = {"configMap", "secret", "projected"}
                nonpersistent = config_types | {"emptyDir", "downwardAPI"}
                if volume_types & config_types:
                    add("Workload configuration volumes", "PENDING_EVIDENCE",
                        "Configuration or projected volume references require target validation; these volumes do not themselves require CSI provisioning.",
                        "Validate referenced configuration, secrets and projected identities in the target manifest and namespace.")
                if volume_types - nonpersistent:
                    add("Workload volume dependencies", "PENDING_EVIDENCE",
                        "Persistent, external, node-local or unclassified volume types require target compatibility evidence.",
                        "Classify each volume and verify target provisioning, PVC and mount requirements."
                        if data_separate else
                        "Classify each volume and verify target provisioning, PVC and data migration requirements.")
        if kind in {"ServiceAccount", "Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding", "Secret"}:
            add("Identity and secrets", "PENDING_EVIDENCE",
                "Target identity, RBAC rules or secret references are not verified.",
                "Compare this identity resource with target authorization and referenced workloads.")
        elif kind in {"Deployment", "StatefulSet", "DaemonSet", "Pod", "Job", "CronJob"}:
            pod = resource.get("pod") if isinstance(resource, dict) else None
            if not isinstance(pod, dict):
                add("Identity and secrets", "PENDING_EVIDENCE",
                    "Source PodSpec identity and image-pull references are not captured.",
                    "Refresh source PodSpec discovery to determine service account, registry and secret requirements.")
            else:
                identity = pod.get("serviceAccountName")
                pull = pod.get("imagePullSecrets")
                pull_count = pod.get("imagePullSecretCount")
                # The sanitized connector reports a count, not the raw PodSpec
                # list. Accept either representation, but never infer zero from
                # absent, malformed or contradictory evidence.
                count_valid = type(pull_count) is int and pull_count >= 0
                list_valid = isinstance(pull, list)
                pull_known = (
                    (list_valid or count_valid)
                    and (pull is None or list_valid)
                    and ("imagePullSecretCount" not in pod or count_valid)
                    and not (list_valid and count_valid and len(pull) != pull_count)
                )
                has_identity = isinstance(identity, str) and bool(identity) and identity != "default"
                has_pull = (list_valid and bool(pull)) or (count_valid and pull_count > 0)
                if has_identity or has_pull:
                    add("Identity and secrets", "PENDING_EVIDENCE",
                        "Workload references a non-default service account or image-pull secrets; target authorization is unverified.",
                        "Verify the named service account, RBAC and registry secret references in the target namespace.")
                elif not pull_known:
                    add("Identity and secrets", "PENDING_EVIDENCE",
                        "Source connector did not report trustworthy image-pull reference evidence.",
                        "Collect or reconcile the sanitized image-pull secret count and references before assessing target access.")
                elif identity != "default":
                    add("Identity and secrets", "PENDING_EVIDENCE",
                        "No explicit image-pull secret references were observed, but the source service account is not confirmed.",
                        "Verify the effective source and target service accounts, including inherited image-pull credentials.")
                # Explicit default identity and zero direct pull references
                # require no specialized named-reference check. This does not
                # verify inherited credentials or target registry authorization.
        if target_snapshot is not None:
            network = evaluate_target_network(
                resource, target_snapshot,
                target_current=target_current,
            )
            if network is not None:
                results.append(network)

            results.extend(evaluate_identity_dependencies(
                resource, resources, planned, target_snapshot,
                target_current=target_current,
            ))
        if kind in {"CustomResourceDefinition", "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"}:
            add("Controllers and dependencies", "PENDING_EVIDENCE",
                "Target API extension or admission controller is not verified.",
                "Discover the matching target CRD or webhook and check its admission behavior.")
        if kind == "StatefulSet":
            add("Stateful storage dependencies", "PENDING_EVIDENCE",
                "Volume templates and persistence dependencies remain unverified.",
                "Verify target PVC mappings, CSI provisioning and mounting."
                if data_separate else
                "Verify target PVC mappings, CSI provisioning and data migration strategy.")
        if not target_current:
            add("Evidence freshness", "PENDING_EVIDENCE",
                "Target evidence is missing, expired or not bound to a current inventory.",
                "Refresh the target inventory and repeat compatibility assessment.")
        statuses = {entry["status"] for entry in results}
        status = ("INCOMPATIBLE" if "INCOMPATIBLE" in statuses else
                  "PENDING_EVIDENCE" if "PENDING_EVIDENCE" in statuses or "PARTIAL" in statuses else
                  "REMEDIATION_REQUIRED" if "REMEDIATION_REQUIRED" in statuses else
                  "COMPATIBLE")
        source_checks = [c for c in results if c["capability"] in {"Source assessment", "Source inventory", "Resource treatment"}]
        target_checks = [c for c in results if c not in source_checks]
        source_status = ("INCOMPATIBLE" if any(c["status"] == "INCOMPATIBLE" for c in source_checks) else
                         "REMEDIATION_REQUIRED" if any(c["status"] == "REMEDIATION_REQUIRED" for c in source_checks) else
                         "PENDING_EVIDENCE" if source_checks else "NO_FINDINGS")
        target_status = ("INCOMPATIBLE" if any(c["status"] == "INCOMPATIBLE" for c in target_checks) else
                         "REMEDIATION_REQUIRED" if any(c["status"] == "REMEDIATION_REQUIRED" for c in target_checks) else
                         "PENDING_EVIDENCE" if any(c["status"] in {"PENDING_EVIDENCE", "PARTIAL"} for c in target_checks) else
                         "COMPATIBLE" if target_checks and all(c["status"] == "COMPATIBLE" for c in target_checks) else
                         "NOT_EVALUATED")
        checks.append({"resource": dict(zip(("apiVersion", "kind", "namespace", "name"), key)),
                       "status": status, "sourceStatus": source_status, "targetStatus": target_status, "checks": results})
    return checks
