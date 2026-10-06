"""Allowlisted Kubernetes inventory sanitization."""

import hashlib
import json


MAX_RESOURCES = 10_000
MAX_INVENTORY_BYTES = 4 * 1024 * 1024

FORBIDDEN_KINDS = {
    "ConfigMap",
    "Event",
    "Secret",
}

WORKLOAD_KINDS = {
    "CronJob",
    "DaemonSet",
    "Deployment",
    "Job",
    "StatefulSet",
}

SUPPORTED_KINDS = WORKLOAD_KINDS | {
    "CustomResourceDefinition",
    "HorizontalPodAutoscaler",
    "Ingress",
    "Namespace",
    "NetworkPolicy",
    "Node",
    "PersistentVolumeClaim",
    "PodDisruptionBudget",
    "Service",
    "StorageClass",
}


class UnsafeInventory(ValueError):
    """Raised when inventory violates the security boundary."""


def mapping(value):
    return value if isinstance(value, dict) else {}


def sequence(value):
    return value if isinstance(value, list) else []


def limited_text(value, maximum=500):
    return value[:maximum] if isinstance(value, str) else None


def annotation_keys(metadata):
    annotations = mapping(metadata.get("annotations"))
    return sorted(
        limited_text(key, 253)
        for key in annotations
        if limited_text(key, 253)
    )[:200]


def common(resource, include_name=True):
    metadata = mapping(resource.get("metadata"))
    value = {
        "apiVersion": limited_text(resource.get("apiVersion"), 100),
        "kind": limited_text(resource.get("kind"), 100),
        "namespace": limited_text(metadata.get("namespace"), 63),
        "annotationKeys": annotation_keys(metadata),
    }
    if include_name:
        value["name"] = limited_text(metadata.get("name"), 253)
    return value


def env_inventory(container):
    result = []
    for variable in sequence(container.get("env"))[:500]:
        variable = mapping(variable)
        source = "LITERAL"
        value_from = mapping(variable.get("valueFrom"))
        if value_from:
            source = next(
                (
                    key
                    for key in (
                        "secretKeyRef",
                        "configMapKeyRef",
                        "fieldRef",
                        "resourceFieldRef",
                    )
                    if key in value_from
                ),
                "OTHER_REFERENCE",
            )
        result.append(
            {
                "name": limited_text(variable.get("name"), 253),
                "source": source,
            }
        )
    return result


def container_inventory(container):
    security = mapping(container.get("securityContext"))
    capabilities = mapping(security.get("capabilities"))

    return {
        "name": limited_text(container.get("name"), 253),
        "image": limited_text(container.get("image"), 1000),
        "ports": [
            {
                "containerPort": port.get("containerPort"),
                "protocol": limited_text(
                    port.get("protocol") or "TCP",
                    10,
                ),
            }
            for port in sequence(container.get("ports"))[:100]
            if isinstance(port, dict)
        ],
        "environment": env_inventory(container),
        "security": {
            "privileged": security.get("privileged") is True,
            "allowPrivilegeEscalation": (
                security.get("allowPrivilegeEscalation") is True
            ),
            "runAsNonRoot": security.get("runAsNonRoot") is True,
            "readOnlyRootFilesystem": (
                security.get("readOnlyRootFilesystem") is True
            ),
            "addedCapabilities": sorted(
                limited_text(item, 100)
                for item in sequence(capabilities.get("add"))
                if limited_text(item, 100)
            )[:100],
        },
        "hasLivenessProbe": isinstance(
            container.get("livenessProbe"),
            dict,
        ),
        "hasReadinessProbe": isinstance(
            container.get("readinessProbe"),
            dict,
        ),
        "hasStartupProbe": isinstance(
            container.get("startupProbe"),
            dict,
        ),
    }


def volume_inventory(volume):
    volume = mapping(volume)
    known_types = (
        "persistentVolumeClaim",
        "hostPath",
        "emptyDir",
        "secret",
        "configMap",
        "projected",
        "downwardAPI",
        "csi",
        "ephemeral",
        "nfs",
    )
    volume_type = next(
        (item for item in known_types if item in volume),
        "other",
    )
    return {
        "name": limited_text(volume.get("name"), 253),
        "type": volume_type,
    }


def pod_inventory(spec):
    spec = mapping(spec)
    pod_security = mapping(spec.get("securityContext"))

    return {
        "serviceAccountName": limited_text(
            spec.get("serviceAccountName"),
            253,
        ),
        "automountServiceAccountToken": spec.get(
            "automountServiceAccountToken"
        ),
        "hostNetwork": spec.get("hostNetwork") is True,
        "hostPID": spec.get("hostPID") is True,
        "hostIPC": spec.get("hostIPC") is True,
        "runAsNonRoot": pod_security.get("runAsNonRoot") is True,
        "nodeSelectorKeys": sorted(
            limited_text(key, 253)
            for key in mapping(spec.get("nodeSelector"))
            if limited_text(key, 253)
        )[:200],
        "containers": [
            container_inventory(item)
            for item in sequence(spec.get("containers"))[:200]
            if isinstance(item, dict)
        ],
        "initContainers": [
            container_inventory(item)
            for item in sequence(spec.get("initContainers"))[:100]
            if isinstance(item, dict)
        ],
        "volumes": [
            volume_inventory(item)
            for item in sequence(spec.get("volumes"))[:500]
        ],
    }


def workload_pod_spec(resource):
    spec = mapping(resource.get("spec"))
    if resource.get("kind") == "CronJob":
        return mapping(
            mapping(
                mapping(spec.get("jobTemplate")).get("spec")
            ).get("template")
        ).get("spec")
    return mapping(mapping(spec.get("template")).get("spec"))


def sanitize_workload(resource):
    spec = mapping(resource.get("spec"))
    result = common(resource)
    result["replicas"] = spec.get("replicas")
    result["pod"] = pod_inventory(workload_pod_spec(resource))
    return result


def sanitize_resource(resource):
    if not isinstance(resource, dict):
        raise UnsafeInventory("Kubernetes resource must be an object.")

    kind = resource.get("kind")
    if kind in FORBIDDEN_KINDS:
        raise UnsafeInventory(
            f"{kind} resources are forbidden in migration inventory."
        )
    if kind not in SUPPORTED_KINDS:
        raise UnsafeInventory(
            "Unsupported Kubernetes resource kind."
        )

    if kind in WORKLOAD_KINDS:
        return sanitize_workload(resource)

    spec = mapping(resource.get("spec"))

    if kind == "Node":
        status = mapping(resource.get("status"))
        node_info = mapping(status.get("nodeInfo"))
        return {
            **common(resource, include_name=False),
            "kubernetesVersion": limited_text(
                node_info.get("kubeletVersion"),
                50,
            ),
            "operatingSystem": limited_text(
                node_info.get("operatingSystem"),
                50,
            ),
            "architecture": limited_text(
                node_info.get("architecture"),
                50,
            ),
        }

    if kind == "Namespace":
        return common(resource)

    if kind == "Service":
        return {
            **common(resource),
            "type": limited_text(
                spec.get("type") or "ClusterIP",
                50,
            ),
            "selectorKeys": sorted(
                limited_text(key, 253)
                for key in mapping(spec.get("selector"))
                if limited_text(key, 253)
            )[:200],
            "ports": [
                {
                    "port": port.get("port"),
                    "targetPort": port.get("targetPort"),
                    "protocol": limited_text(
                        port.get("protocol") or "TCP",
                        10,
                    ),
                }
                for port in sequence(spec.get("ports"))[:100]
                if isinstance(port, dict)
            ],
        }

    if kind == "Ingress":
        paths = []
        for rule in sequence(spec.get("rules"))[:500]:
            http = mapping(mapping(rule).get("http"))
            for path in sequence(http.get("paths"))[:500]:
                path = mapping(path)
                paths.append(
                    {
                        "pathType": limited_text(
                            path.get("pathType"),
                            50,
                        )
                    }
                )
        return {
            **common(resource),
            "ingressClassName": limited_text(
                spec.get("ingressClassName"),
                253,
            ),
            "ruleCount": len(sequence(spec.get("rules"))),
            "tlsEntryCount": len(sequence(spec.get("tls"))),
            "paths": paths,
        }

    if kind == "PersistentVolumeClaim":
        resources = mapping(spec.get("resources"))
        requests = mapping(resources.get("requests"))
        return {
            **common(resource),
            "accessModes": sorted(
                limited_text(item, 50)
                for item in sequence(spec.get("accessModes"))
                if limited_text(item, 50)
            ),
            "storageClassName": limited_text(
                spec.get("storageClassName"),
                253,
            ),
            "volumeMode": limited_text(
                spec.get("volumeMode"),
                50,
            ),
            "requestedStorage": limited_text(
                requests.get("storage"),
                50,
            ),
        }

    if kind == "StorageClass":
        return {
            **common(resource),
            "provisioner": limited_text(
                resource.get("provisioner"),
                253,
            ),
            "reclaimPolicy": limited_text(
                resource.get("reclaimPolicy"),
                50,
            ),
            "volumeBindingMode": limited_text(
                resource.get("volumeBindingMode"),
                100,
            ),
        }

    if kind == "CustomResourceDefinition":
        names = mapping(spec.get("names"))
        return {
            **common(resource),
            "group": limited_text(spec.get("group"), 253),
            "scope": limited_text(spec.get("scope"), 50),
            "customKind": limited_text(names.get("kind"), 100),
            "versions": [
                {
                    "name": limited_text(
                        mapping(version).get("name"),
                        50,
                    ),
                    "served": mapping(version).get("served") is True,
                    "storage": mapping(version).get("storage") is True,
                }
                for version in sequence(spec.get("versions"))[:100]
            ],
        }

    if kind == "HorizontalPodAutoscaler":
        target = mapping(spec.get("scaleTargetRef"))
        return {
            **common(resource),
            "minimumReplicas": spec.get("minReplicas"),
            "maximumReplicas": spec.get("maxReplicas"),
            "targetKind": limited_text(target.get("kind"), 100),
        }

    if kind == "PodDisruptionBudget":
        return {
            **common(resource),
            "minimumAvailable": spec.get("minAvailable"),
            "maximumUnavailable": spec.get("maxUnavailable"),
        }

    if kind == "NetworkPolicy":
        return {
            **common(resource),
            "policyTypes": sorted(
                limited_text(item, 50)
                for item in sequence(spec.get("policyTypes"))
                if limited_text(item, 50)
            ),
            "ingressRuleCount": len(sequence(spec.get("ingress"))),
            "egressRuleCount": len(sequence(spec.get("egress"))),
        }

    raise UnsafeInventory("Unsupported Kubernetes resource kind.")


def finalize_inventory(sanitized):
    if len(sanitized) > MAX_RESOURCES:
        raise UnsafeInventory("Inventory resource limit exceeded.")

    resources = list(sanitized)
    resources.sort(
        key=lambda item: (
            item.get("kind") or "",
            item.get("namespace") or "",
            item.get("name") or "",
        )
    )

    payload = {
        "schemaVersion": 1,
        "sensitiveDataIncluded": False,
        "resources": resources,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    if len(encoded) > MAX_INVENTORY_BYTES:
        raise UnsafeInventory("Inventory payload limit exceeded.")

    payload["inventoryDigest"] = hashlib.sha256(encoded).hexdigest()
    return payload


def build_inventory(resources):
    if len(resources) > MAX_RESOURCES:
        raise UnsafeInventory("Inventory resource limit exceeded.")

    return finalize_inventory(
        [sanitize_resource(item) for item in resources]
    )
