"""Deterministic, trusted migration feasibility assessment."""

from collections import Counter
from datetime import datetime, timezone


DISPOSITION_RANK = {
    "SEAMLESS": 0,
    "AUTOMATED_CHANGE": 1,
    "MANUAL_CHANGE": 2,
    "BLOCKER": 3,
}

DEPRECATED_APIS = {
    "extensions/v1beta1",
    "apps/v1beta1",
    "apps/v1beta2",
    "networking.k8s.io/v1beta1",
    "policy/v1beta1",
    "autoscaling/v2beta1",
    "autoscaling/v2beta2",
}

SUPPORTED_ARCHITECTURES = {"amd64", "arm64"}


def finding(
    code,
    severity,
    category,
    disposition,
    message,
    remediation=None,
    resource=None,
):
    result = {
        "code": code,
        "severity": severity,
        "category": category,
        "disposition": disposition,
        "message": message,
    }

    if remediation:
        result["remediation"] = remediation

    if resource:
        if resource.get("namespace"):
            result["namespace"] = resource["namespace"]
        if resource.get("kind"):
            result["resourceKind"] = resource["kind"]
        if resource.get("name"):
            result["resourceName"] = resource["name"]

    return result


def add_resource_finding(
    findings,
    dispositions,
    index,
    resource,
    **details,
):
    item = finding(resource=resource, **details)
    findings.append(item)

    disposition = item["disposition"]
    if (
        DISPOSITION_RANK[disposition]
        > DISPOSITION_RANK[dispositions[index]]
    ):
        dispositions[index] = disposition


def pod_containers(pod):
    return [
        *pod.get("initContainers", []),
        *pod.get("containers", []),
    ]


def assess_resource(index, resource, findings, dispositions):
    api_version = resource.get("apiVersion")
    kind = resource.get("kind")

    if api_version in DEPRECATED_APIS:
        add_resource_finding(
            findings,
            dispositions,
            index,
            resource,
            code="UNSUPPORTED_KUBERNETES_API",
            severity="BLOCKER",
            category="KUBERNETES_API",
            disposition="BLOCKER",
            message=(
                f"{kind} uses Kubernetes API {api_version}, "
                "which is not supported by the target baseline."
            ),
            remediation=(
                "Convert the manifest to a currently supported "
                "Kubernetes API before migration."
            ),
        )

    if kind == "Node":
        architecture = resource.get("architecture")
        if (
            architecture
            and architecture not in SUPPORTED_ARCHITECTURES
        ):
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="UNSUPPORTED_NODE_ARCHITECTURE",
                severity="BLOCKER",
                category="WORKLOAD",
                disposition="BLOCKER",
                message=(
                    f"Node architecture {architecture} is not "
                    "supported by the EKS migration baseline."
                ),
                remediation=(
                    "Rebuild workload images for amd64 or arm64 "
                    "and select compatible EKS node groups."
                ),
            )
        return

    if kind in {
        "Deployment",
        "StatefulSet",
        "DaemonSet",
        "Job",
        "CronJob",
    }:
        pod = resource.get("pod") or {}

        host_features = [
            feature
            for feature in ("hostNetwork", "hostPID", "hostIPC")
            if pod.get(feature) is True
        ]
        if host_features:
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="HOST_NAMESPACE_USAGE",
                severity="WARNING",
                category="SECURITY",
                disposition="MANUAL_CHANGE",
                message=(
                    "Workload uses host-level namespaces: "
                    + ", ".join(host_features)
                    + "."
                ),
                remediation=(
                    "Remove the host namespace dependency or obtain "
                    "an explicit target security-policy exception."
                ),
            )

        service_account = pod.get("serviceAccountName")
        if service_account and service_account != "default":
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="SERVICE_ACCOUNT_MAPPING_REQUIRED",
                severity="WARNING",
                category="IDENTITY",
                disposition="MANUAL_CHANGE",
                message=(
                    "Workload uses a named Kubernetes service account."
                ),
                remediation=(
                    "Map the service account to an approved EKS "
                    "identity and IAM role."
                ),
            )

        volume_types = {
            volume.get("type")
            for volume in pod.get("volumes", [])
            if isinstance(volume, dict)
        }

        if "hostPath" in volume_types:
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="HOST_PATH_STORAGE_REDESIGN",
                severity="WARNING",
                category="STORAGE",
                disposition="MANUAL_CHANGE",
                message="Workload depends on node-local hostPath storage.",
                remediation=(
                    "Replace hostPath with EBS, EFS, or another "
                    "approved persistent storage service."
                ),
            )

        if "nfs" in volume_types:
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="NFS_TARGET_VALIDATION_REQUIRED",
                severity="WARNING",
                category="STORAGE",
                disposition="MANUAL_CHANGE",
                message="Workload depends on an NFS volume.",
                remediation=(
                    "Validate target network access and map the "
                    "volume to an approved EFS or NFS endpoint."
                ),
            )

        if {"secret", "configMap"} & volume_types:
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="CONFIGURATION_RECREATION_REQUIRED",
                severity="WARNING",
                category="SECURITY",
                disposition="MANUAL_CHANGE",
                message=(
                    "Workload references Secrets or ConfigMaps whose "
                    "contents were intentionally excluded."
                ),
                remediation=(
                    "Recreate configuration and secrets through the "
                    "approved target secret-management process."
                ),
            )

        privileged = False
        external_configuration = False

        for container in pod_containers(pod):
            security = container.get("security") or {}
            privileged = (
                privileged
                or security.get("privileged") is True
                or security.get("allowPrivilegeEscalation") is True
            )

            for variable in container.get("environment", []):
                if variable.get("source") in {
                    "secretKeyRef",
                    "configMapKeyRef",
                }:
                    external_configuration = True

        if privileged:
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="PRIVILEGED_WORKLOAD_REVIEW",
                severity="WARNING",
                category="SECURITY",
                disposition="MANUAL_CHANGE",
                message=(
                    "Workload requests privileged execution or "
                    "privilege escalation."
                ),
                remediation=(
                    "Harden the container security context or obtain "
                    "an explicit EKS security-policy exception."
                ),
            )

        if external_configuration:
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="EXTERNAL_CONFIGURATION_REQUIRED",
                severity="WARNING",
                category="SECURITY",
                disposition="MANUAL_CHANGE",
                message=(
                    "Environment variables depend on target-side "
                    "Secrets or ConfigMaps."
                ),
                remediation=(
                    "Bootstrap the required target configuration "
                    "before workload deployment."
                ),
            )

    elif kind == "Service":
        if resource.get("type") == "LoadBalancer":
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="LOAD_BALANCER_TRANSLATION",
                severity="WARNING",
                category="NETWORK",
                disposition="AUTOMATED_CHANGE",
                message=(
                    "LoadBalancer service requires target-specific "
                    "AWS load-balancer configuration."
                ),
                remediation=(
                    "Generate approved AWS Load Balancer Controller "
                    "annotations during migration planning."
                ),
            )

    elif kind == "Ingress":
        add_resource_finding(
            findings,
            dispositions,
            index,
            resource,
            code="INGRESS_TRANSLATION",
            severity="WARNING",
            category="NETWORK",
            disposition="AUTOMATED_CHANGE",
            message=(
                "Ingress requires translation to the approved EKS "
                "ingress implementation."
            ),
            remediation=(
                "Generate an AWS Load Balancer Controller or approved "
                "ingress mapping."
            ),
        )

    elif kind == "PersistentVolumeClaim":
        disposition = (
            "AUTOMATED_CHANGE"
            if resource.get("requestedStorage")
            else "MANUAL_CHANGE"
        )
        add_resource_finding(
            findings,
            dispositions,
            index,
            resource,
            code="PERSISTENT_STORAGE_MAPPING",
            severity="WARNING",
            category="STORAGE",
            disposition=disposition,
            message=(
                "PersistentVolumeClaim requires target storage-class "
                "mapping."
            ),
            remediation=(
                "Map the claim to an approved EBS or EFS storage "
                "class and plan data migration separately."
            ),
        )

    elif kind == "StorageClass":
        add_resource_finding(
            findings,
            dispositions,
            index,
            resource,
            code="STORAGE_CLASS_TRANSLATION",
            severity="WARNING",
            category="STORAGE",
            disposition="MANUAL_CHANGE",
            message=(
                "Source storage class cannot be copied directly "
                "between infrastructure platforms."
            ),
            remediation=(
                "Select an approved EKS CSI provisioner and map "
                "dependent claims."
            ),
        )

    elif kind == "CustomResourceDefinition":
        add_resource_finding(
            findings,
            dispositions,
            index,
            resource,
            code="CUSTOM_RESOURCE_OPERATOR_REQUIRED",
            severity="WARNING",
            category="WORKLOAD",
            disposition="MANUAL_CHANGE",
            message=(
                "CustomResourceDefinition requires its owning "
                "controller or operator on the target."
            ),
            remediation=(
                "Install and validate a compatible operator before "
                "migrating custom resources."
            ),
        )


def score(dispositions, target_blockers, target_warnings):
    total = max(len(dispositions), 1)
    counts = Counter(dispositions)

    weighted_risk = (
        counts["AUTOMATED_CHANGE"] * 10
        + counts["MANUAL_CHANGE"] * 35
        + counts["BLOCKER"] * 100
    )
    resource_penalty = round(weighted_risk / total)
    target_penalty = target_blockers * 30 + target_warnings * 10

    result = max(0, 100 - resource_penalty - target_penalty)
    if counts["BLOCKER"] or target_blockers:
        result = min(result, 75)

    return result


def assess(source_inventory, target_runtime, target_configuration):
    resources = source_inventory["resources"]
    findings = []
    dispositions = ["SEAMLESS"] * len(resources)

    for index, resource in enumerate(resources):
        assess_resource(
            index,
            resource,
            findings,
            dispositions,
        )

    target_status = target_runtime.get("status")
    target_blockers = 0
    target_warnings = 0

    if target_status in {"NOT_REPORTED", "STALE"}:
        target_blockers += 1
        findings.append(
            finding(
                code="TARGET_RUNTIME_UNAVAILABLE",
                severity="BLOCKER",
                category="WORKLOAD",
                disposition="BLOCKER",
                message=(
                    "The selected EKS target does not have a fresh "
                    "runtime inventory."
                ),
                remediation=(
                    "Restore the target cluster connector and obtain "
                    "a fresh healthy runtime inventory."
                ),
            )
        )
    elif target_status != "READY":
        target_warnings += 1
        findings.append(
            finding(
                code="TARGET_RUNTIME_DEGRADED",
                severity="WARNING",
                category="WORKLOAD",
                disposition="MANUAL_CHANGE",
                message=(
                    "The selected EKS target is not reporting READY."
                ),
                remediation=(
                    "Resolve target cluster health warnings before "
                    "migration."
                ),
            )
        )

    metrics = target_runtime.get("metrics") or {}
    node_count = metrics.get("nodeCount")
    ready_nodes = metrics.get("readyNodeCount")

    if (
        isinstance(node_count, int)
        and isinstance(ready_nodes, int)
        and ready_nodes < node_count
    ):
        target_blockers += 1
        findings.append(
            finding(
                code="TARGET_NODES_NOT_READY",
                severity="BLOCKER",
                category="WORKLOAD",
                disposition="BLOCKER",
                message=(
                    f"Only {ready_nodes} of {node_count} target "
                    "nodes are ready."
                ),
                remediation=(
                    "Restore all target nodes to Ready state before "
                    "migration."
                ),
            )
        )

    classification = Counter(dispositions)
    kind_counts = Counter(
        resource.get("kind", "Unknown")
        for resource in resources
    )

    compatibility_score = score(
        dispositions,
        target_blockers,
        target_warnings,
    )

    observed_at = datetime.now(timezone.utc).isoformat()

    return {
        "reportSchemaVersion": 1,
        "observedAt": observed_at,
        "sourceKubernetesVersion": (
            source_inventory["sourceKubernetesVersion"]
        ),
        "inventoryDigest": source_inventory["inventoryDigest"],
        "compatibilityScore": compatibility_score,
        "containsBlockers": any(
            item["severity"] == "BLOCKER"
            for item in findings
        ),
        "inventorySummary": {
            "resourceCount": len(resources),
            "resourceKinds": dict(sorted(kind_counts.items())),
            "classification": {
                key: classification.get(key, 0)
                for key in DISPOSITION_RANK
            },
            "target": {
                "clusterId": target_configuration.get("clusterId"),
                "clusterName": target_configuration.get("clusterName"),
                "status": target_status,
                "nodeCount": node_count,
                "readyNodeCount": ready_nodes,
            },
        },
        "findings": findings,
    }
