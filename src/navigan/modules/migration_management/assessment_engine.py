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

RUNBOOKS = {
    "TARGET_NODES_NOT_READY": {
        "targetTreatment": "Healthy target node group with every node reporting Ready.",
        "resolutionSteps": [
            "Identify the target nodes that are NotReady and review their conditions and events.",
            "Correct node-group capacity, networking, IAM, bootstrap, disk, or kubelet failures.",
            "Replace an unrecoverable node through the managed node group.",
        ],
        "validationSteps": [
            "Confirm every target node reports Ready.",
            "Refresh the target connector inventory and rerun the assessment.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Platform operations",
    },
    "HOST_NAMESPACE_USAGE": {
        "targetTreatment": "Pod isolation compatible with the target security baseline.",
        "resolutionSteps": [
            "Determine whether the resource is an application workload or a source platform add-on.",
            "Exclude source CNI and platform add-ons that have a target-managed replacement.",
            "For application workloads, remove host namespace use or document an approved exception.",
        ],
        "validationSteps": [
            "Confirm the translated pod specification no longer requests unapproved host namespaces.",
            "Validate the workload against the target admission and pod-security policies.",
        ],
        "automationLevel": "MANUAL",
        "ownerTeam": "Platform security",
    },
    "SERVICE_ACCOUNT_MAPPING_REQUIRED": {
        "targetTreatment": "Kubernetes service account mapped to approved target workload identity.",
        "resolutionSteps": [
            "Identify the cloud and Kubernetes permissions used by the service account.",
            "Create a least-privilege target IAM policy and EKS Pod Identity or IRSA association.",
            "Update the target service account and workload references.",
        ],
        "validationSteps": [
            "Verify the pod receives only the intended AWS identity.",
            "Run an application authorization test without static cloud credentials.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Identity and access",
    },
    "HOST_PATH_STORAGE_REDESIGN": {
        "targetTreatment": "EBS, EFS, object storage, or another approved managed storage service.",
        "resolutionSteps": [
            "Determine whether the path contains persistent data, cache data, or platform state.",
            "Select EBS for single-writer block storage or EFS for shared file storage.",
            "Create the target StorageClass and PersistentVolumeClaim mapping.",
        ],
        "validationSteps": [
            "Verify the target claim binds and mounts successfully.",
            "Test data integrity, permissions, performance, backup, and restore.",
        ],
        "automationLevel": "MANUAL",
        "ownerTeam": "Data platform",
    },
    "NFS_TARGET_VALIDATION_REQUIRED": {
        "targetTreatment": "Reachable and approved EFS or NFS service with equivalent access semantics.",
        "resolutionSteps": [
            "Document the source export, access mode, capacity, performance, and network requirements.",
            "Provision or select the target file service and CSI configuration.",
            "Plan data replication and update the target PersistentVolume definition.",
        ],
        "validationSteps": [
            "Mount the target volume from representative workloads.",
            "Validate permissions, throughput, failover, backup, and restore.",
        ],
        "automationLevel": "MANUAL",
        "ownerTeam": "Data platform",
    },
    "CONFIGURATION_RECREATION_REQUIRED": {
        "targetTreatment": "Configuration recreated through an approved target configuration and secret-management process.",
        "resolutionSteps": [
            "Inventory required Secret and ConfigMap names and consuming workloads without reading values.",
            "Identify the approved source of truth for each configuration item.",
            "Create target configuration through GitOps, External Secrets, Secrets Manager, or the approved delivery process.",
        ],
        "validationSteps": [
            "Confirm every referenced key exists in the target.",
            "Test application startup while ensuring sensitive values remain absent from Navigan evidence.",
        ],
        "automationLevel": "MANUAL",
        "ownerTeam": "Application team",
    },
    "EXTERNAL_CONFIGURATION_REQUIRED": {
        "targetTreatment": "Target-side Secret and ConfigMap references available before workload deployment.",
        "resolutionSteps": [
            "Map every environment reference to its approved target source.",
            "Create the target objects or external-secret definitions.",
            "Sequence configuration delivery before dependent workloads.",
        ],
        "validationSteps": [
            "Verify all references resolve without exposing values.",
            "Confirm the workload starts successfully with target configuration.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Application team",
    },
    "PERSISTENT_STORAGE_MAPPING": {
        "targetTreatment": "Approved EKS CSI StorageClass and a separately governed data-transfer plan.",
        "resolutionSteps": [
            "Classify the volume by access mode, capacity, performance, retention, and recovery requirements.",
            "Map the claim to an approved EBS or EFS CSI StorageClass.",
            "Define snapshot, replication, backup/restore, or application-level data transfer.",
        ],
        "validationSteps": [
            "Provision and mount a target test claim.",
            "Validate data consistency and recovery before cutover.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Data platform",
    },
    "LOAD_BALANCER_TRANSLATION": {
        "targetTreatment": "AWS Load Balancer Controller-compatible Service configuration.",
        "resolutionSteps": [
            "Select ALB or NLB based on protocol, traffic, TLS, and source-IP requirements.",
            "Generate approved controller annotations and security-group settings.",
            "Map DNS, certificates, health checks, and traffic policies.",
        ],
        "validationSteps": [
            "Confirm the target load balancer is healthy and reachable.",
            "Validate TLS, DNS, health checks, and client source-IP behavior.",
        ],
        "automationLevel": "AUTOMATED",
        "ownerTeam": "Networking",
    },
    "INGRESS_TRANSLATION": {
        "targetTreatment": "Approved EKS ingress controller, Gateway API, or ALB configuration.",
        "resolutionSteps": [
            "Inventory ingress classes, routes, TLS references, rewrites, and controller-specific annotations.",
            "Translate them to the approved target ingress implementation.",
            "Map certificates, DNS records, WAF, and external traffic dependencies.",
        ],
        "validationSteps": [
            "Test every hostname and route in a non-production target environment.",
            "Verify TLS, redirects, timeouts, health checks, and policy enforcement.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Networking",
    },
    "UNSUPPORTED_KUBERNETES_API": {
        "targetTreatment": "Manifest using an API version served by the target Kubernetes version.",
        "resolutionSteps": [
            "Identify the replacement API and review schema changes.",
            "Convert the manifest or Helm template to the supported API.",
            "Test server-side validation against the target cluster.",
        ],
        "validationSteps": [
            "Run a server-side dry run against the target.",
            "Confirm the deprecated API is absent from generated manifests.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Application platform",
    },
    "UNSUPPORTED_NODE_ARCHITECTURE": {
        "targetTreatment": "Multi-architecture or target-architecture image running on an approved node group.",
        "resolutionSteps": [
            "Identify workloads tied to the unsupported source architecture.",
            "Build and publish amd64, arm64, or multi-architecture images.",
            "Select compatible target node groups and scheduling labels.",
        ],
        "validationSteps": [
            "Inspect the image manifest for the required architectures.",
            "Deploy and execute the workload on each intended target architecture.",
        ],
        "automationLevel": "MANUAL",
        "ownerTeam": "Application team",
    },
    "PRIVILEGED_WORKLOAD_REVIEW": {
        "targetTreatment": "Restricted container security context approved by target policy.",
        "resolutionSteps": [
            "Remove privileged mode, unnecessary Linux capabilities, and privilege escalation.",
            "Set a non-root user, read-only root filesystem, and least-privilege seccomp profile.",
            "Request a documented exception only when the workload cannot be redesigned.",
        ],
        "validationSteps": [
            "Validate the manifest against target pod-security and admission policies.",
            "Run the workload and confirm required functionality without elevated privileges.",
        ],
        "automationLevel": "MANUAL",
        "ownerTeam": "Platform security",
    },
    "RESOURCE_REQUIREMENTS_MISSING": {
        "targetTreatment": "Explicit CPU and memory requests and limits sized for the target.",
        "resolutionSteps": [
            "Collect representative CPU and memory utilization and peak demand.",
            "Set requests for scheduling and limits according to the target reliability policy.",
            "Review autoscaling thresholds after applying the new resource profile.",
        ],
        "validationSteps": [
            "Confirm pods schedule without excessive throttling or eviction.",
            "Observe utilization and autoscaling under representative load.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Application team",
    },
    "MUTABLE_IMAGE_REFERENCE": {
        "targetTreatment": "Immutable image digest available from an approved target registry.",
        "resolutionSteps": [
            "Resolve the deployed image to its immutable digest.",
            "Scan the image and copy or replicate it to the approved target registry.",
            "Update the target manifest to reference the digest.",
        ],
        "validationSteps": [
            "Verify every target node architecture can pull and run the image.",
            "Confirm vulnerability, signature, provenance, and policy checks pass.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Application security",
    },
    "SCHEDULING_CONSTRAINT_REVIEW": {
        "targetTreatment": "Scheduling rules mapped to target labels, zones, capacity types, and node groups.",
        "resolutionSteps": [
            "Review node selectors, affinity, tolerations, topology spread, priority, and runtime class.",
            "Map source labels and taints to approved target node groups.",
            "Remove constraints that reference source-only infrastructure.",
        ],
        "validationSteps": [
            "Run a server-side dry run and scheduling test on the target.",
            "Verify replicas distribute across the required zones and failure domains.",
        ],
        "automationLevel": "MANUAL",
        "ownerTeam": "Platform engineering",
    },
    "RBAC_TARGET_MAPPING_REQUIRED": {
        "targetTreatment": "Least-privilege Kubernetes RBAC and target cloud identity mapping.",
        "resolutionSteps": [
            "Review roles, bindings, subjects, and service-account usage.",
            "Remove broad permissions and map cloud access through target workload identity.",
            "Generate target Roles, ClusterRoles, bindings, and identity associations.",
        ],
        "validationSteps": [
            "Test allowed and denied actions for every migrated identity.",
            "Confirm no source cloud credentials or obsolete subjects remain.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Identity and access",
    },
    "ADMISSION_WEBHOOK_REVIEW_REQUIRED": {
        "targetTreatment": "Compatible, highly available admission policy or target-native replacement.",
        "resolutionSteps": [
            "Identify the owning controller, certificates, failure policy, and intercepted resources.",
            "Install a compatible target version or map the policy to a target-native control.",
            "Sequence webhook activation after its controller and certificate dependencies are ready.",
        ],
        "validationSteps": [
            "Verify admission requests succeed during controller availability and failure tests.",
            "Confirm the webhook does not block target bootstrap or migration workloads.",
        ],
        "automationLevel": "MANUAL",
        "ownerTeam": "Platform security",
    },
    "STORAGE_CLASS_TRANSLATION": {
        "targetTreatment": "Approved target CSI provisioner and StorageClass policy.",
        "resolutionSteps": [
            "Map source provisioner, binding mode, reclaim policy, encryption, and expansion behavior.",
            "Select or create the equivalent EBS or EFS CSI StorageClass.",
            "Associate dependent claims with the target class.",
        ],
        "validationSteps": [
            "Provision, expand, snapshot, restore, and delete a test claim.",
            "Confirm availability-zone binding and reclaim behavior.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Data platform",
    },
    "CUSTOM_RESOURCE_OPERATOR_REQUIRED": {
        "targetTreatment": "Compatible operator and CRDs installed before custom resources.",
        "resolutionSteps": [
            "Identify the CRD owner, operator version, installation method, and dependencies.",
            "Confirm compatibility with the target Kubernetes version and security baseline.",
            "Install the operator before restoring its custom resources.",
        ],
        "validationSteps": [
            "Confirm CRDs are Established and the operator is healthy.",
            "Create or reconcile a representative custom resource.",
        ],
        "automationLevel": "MANUAL",
        "ownerTeam": "Application platform",
    },
    "TARGET_RUNTIME_UNAVAILABLE": {
        "targetTreatment": "Fresh authenticated target runtime inventory.",
        "resolutionSteps": [
            "Restore the target connector and verify outbound API connectivity.",
            "Confirm its credential is active and its Kubernetes RBAC is valid.",
            "Collect a new target runtime snapshot.",
        ],
        "validationSteps": [
            "Confirm the target inventory timestamp is within the freshness policy.",
            "Rerun assessment with a READY target runtime.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Platform operations",
    },
    "TARGET_RUNTIME_DEGRADED": {
        "targetTreatment": "Target cluster and required platform services reporting healthy.",
        "resolutionSteps": [
            "Review target node, pod, connector, and warning-event health.",
            "Correct degraded platform services and capacity constraints.",
            "Refresh the runtime inventory.",
        ],
        "validationSteps": [
            "Confirm the target status reports READY.",
            "Rerun the assessment and verify the warning is cleared.",
        ],
        "automationLevel": "ASSISTED",
        "ownerTeam": "Platform operations",
    },
}


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

    result.update(RUNBOOKS.get(code, {}))

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
        resource_requirements_missing = False
        mutable_image_reference = False

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

            requirements = container.get("resources") or {}
            if not requirements.get("requests") or not requirements.get(
                "limits"
            ):
                resource_requirements_missing = True

            image = container.get("image")
            if isinstance(image, str) and "@sha256:" not in image:
                mutable_image_reference = True

        if resource_requirements_missing:
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="RESOURCE_REQUIREMENTS_MISSING",
                severity="WARNING",
                category="WORKLOAD",
                disposition="MANUAL_CHANGE",
                message=(
                    "Container CPU or memory requests and limits are incomplete."
                ),
                remediation=(
                    "Size explicit CPU and memory requests and limits using "
                    "representative utilization data."
                ),
            )

        if mutable_image_reference:
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="MUTABLE_IMAGE_REFERENCE",
                severity="WARNING",
                category="SECURITY",
                disposition="MANUAL_CHANGE",
                message="Container image is not pinned to an immutable digest.",
                remediation=(
                    "Resolve, scan, replicate, and deploy the image by digest "
                    "from an approved target registry."
                ),
            )

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

        affinity = pod.get("affinity") or {}
        if (
            pod.get("nodeSelectorKeys")
            or pod.get("tolerations")
            or pod.get("topologySpreadConstraints")
            or any(affinity.values())
            or pod.get("priorityClassName")
            or pod.get("runtimeClassName")
        ):
            add_resource_finding(
                findings,
                dispositions,
                index,
                resource,
                code="SCHEDULING_CONSTRAINT_REVIEW",
                severity="WARNING",
                category="WORKLOAD",
                disposition="MANUAL_CHANGE",
                message=(
                    "Workload scheduling constraints require target node-group "
                    "and failure-domain mapping."
                ),
                remediation=(
                    "Map selectors, affinity, tolerations, topology spread, "
                    "priority, and runtime class to the target."
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

    elif kind in {
        "ServiceAccount",
        "Role",
        "RoleBinding",
        "ClusterRole",
        "ClusterRoleBinding",
    }:
        add_resource_finding(
            findings,
            dispositions,
            index,
            resource,
            code="RBAC_TARGET_MAPPING_REQUIRED",
            severity="WARNING",
            category="IDENTITY",
            disposition="MANUAL_CHANGE",
            message="Kubernetes access configuration requires target mapping.",
            remediation=(
                "Review and recreate least-privilege Kubernetes RBAC and "
                "target workload identity associations."
            ),
        )

    elif kind in {
        "MutatingWebhookConfiguration",
        "ValidatingWebhookConfiguration",
    }:
        add_resource_finding(
            findings,
            dispositions,
            index,
            resource,
            code="ADMISSION_WEBHOOK_REVIEW_REQUIRED",
            severity="WARNING",
            category="SECURITY",
            disposition="MANUAL_CHANGE",
            message="Admission webhook requires a compatible target deployment.",
            remediation=(
                "Install or replace the owning controller and validate its "
                "certificates, availability, rules, and failure policy."
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
                "podCount": metrics.get("podCount"),
                "readyPodCount": metrics.get("readyPodCount"),
                "containerRestartCount": metrics.get(
                    "containerRestartCount"
                ),
                "warningEventCount": metrics.get("warningEventCount"),
            },
        },
        "findings": findings,
    }
