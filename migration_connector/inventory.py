"""Allowlisted Kubernetes inventory sanitization."""

import hashlib
import json


MAX_RESOURCES = 10_000
MAX_INVENTORY_BYTES = 4 * 1024 * 1024

FORBIDDEN_KINDS = {
    "Event",
}

WORKLOAD_KINDS = {
    "CronJob",
    "DaemonSet",
    "Deployment",
    "Job",
    "StatefulSet",
}

SUPPORTED_KINDS = WORKLOAD_KINDS | {
    "ClusterRole",
    "ClusterRoleBinding",
    "ConfigMap",
    "CustomResourceDefinition",
    "HorizontalPodAutoscaler",
    "Ingress",
    "MutatingWebhookConfiguration",
    "Namespace",
    "NetworkPolicy",
    "Node",
    "PersistentVolumeClaim",
    "PodDisruptionBudget",
    "Role",
    "RoleBinding",
    "Service",
    "ServiceAccount",
    "Secret",
    "StorageClass",
    "ValidatingWebhookConfiguration",
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

def label_keys(metadata):
    labels = mapping(metadata.get("labels"))
    return sorted(
        limited_text(key, 253)
        for key in labels
        if limited_text(key, 253)
    )[:200]


def common(resource, include_name=True):
    metadata = mapping(resource.get("metadata"))
    value = {
        "apiVersion": limited_text(resource.get("apiVersion"), 100),
        "kind": limited_text(resource.get("kind"), 100),
        "namespace": limited_text(metadata.get("namespace"), 63),
        "annotationKeys": annotation_keys(metadata),
        "labelKeys": label_keys(metadata),
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
    resources = mapping(container.get("resources"))

    return {
        "name": limited_text(container.get("name"), 253),
        "image": limited_text(container.get("image"), 1000),
        "imagePullPolicy": limited_text(
            container.get("imagePullPolicy"),
            50,
        ),
        "ports": [
            {
                "containerPort": port.get("containerPort"),
                "hostPort": port.get("hostPort"),
                "protocol": limited_text(
                    port.get("protocol") or "TCP",
                    10,
                ),
            }
            for port in sequence(container.get("ports"))[:100]
            if isinstance(port, dict)
        ],
        "resources": {
            "requests": {
                limited_text(key, 100): limited_text(value, 100)
                if isinstance(value, str)
                else value
                for key, value in mapping(resources.get("requests")).items()
                if limited_text(key, 100)
                and isinstance(value, (str, int, float))
            },
            "limits": {
                limited_text(key, 100): limited_text(value, 100)
                if isinstance(value, str)
                else value
                for key, value in mapping(resources.get("limits")).items()
                if limited_text(key, 100)
                and isinstance(value, (str, int, float))
            },
        },
        "volumeMounts": [
            {
                "name": limited_text(mount.get("name"), 253),
                "mountPath": limited_text(mount.get("mountPath"), 500),
                "subPath": limited_text(mount.get("subPath"), 500),
                "readOnly": mount.get("readOnly") is True,
            }
            for mount in sequence(container.get("volumeMounts"))[:500]
            if isinstance(mount, dict)
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
        "priorityClassName": limited_text(
            spec.get("priorityClassName"),
            253,
        ),
        "runtimeClassName": limited_text(
            spec.get("runtimeClassName"),
            253,
        ),
        "schedulerName": limited_text(spec.get("schedulerName"), 253),
        "dnsPolicy": limited_text(spec.get("dnsPolicy"), 100),
        "terminationGracePeriodSeconds": spec.get(
            "terminationGracePeriodSeconds"
        ),
        "imagePullSecretCount": len(sequence(spec.get("imagePullSecrets"))),
        "affinity": {
            "nodeAffinity": bool(
                mapping(spec.get("affinity")).get("nodeAffinity")
            ),
            "podAffinity": bool(
                mapping(spec.get("affinity")).get("podAffinity")
            ),
            "podAntiAffinity": bool(
                mapping(spec.get("affinity")).get("podAntiAffinity")
            ),
        },
        "tolerations": [
            {
                "key": limited_text(item.get("key"), 253),
                "operator": limited_text(item.get("operator"), 50),
                "effect": limited_text(item.get("effect"), 50),
            }
            for item in sequence(spec.get("tolerations"))[:200]
            if isinstance(item, dict)
        ],
        "topologySpreadConstraints": [
            {
                "topologyKey": limited_text(item.get("topologyKey"), 253),
                "whenUnsatisfiable": limited_text(
                    item.get("whenUnsatisfiable"),
                    100,
                ),
            }
            for item in sequence(
                spec.get("topologySpreadConstraints")
            )[:200]
            if isinstance(item, dict)
        ],
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
    result["strategyType"] = limited_text(
        mapping(spec.get("strategy")).get("type")
        or mapping(spec.get("updateStrategy")).get("type"),
        100,
    )
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

    if kind == "ConfigMap":
        return {
            **common(resource),
            "immutable": resource.get("immutable") is True,
            "dataKeyNames": sorted(
                limited_text(key, 253)
                for key in mapping(resource.get("data"))
                if limited_text(key, 253)
            )[:500],
            "binaryDataKeyNames": sorted(
                limited_text(key, 253)
                for key in mapping(resource.get("binaryData"))
                if limited_text(key, 253)
            )[:500],
        }

    if kind == "Secret":
        return {
            **common(resource),
            "secretType": limited_text(resource.get("type"), 253),
            "immutable": resource.get("immutable") is True,
            "dataKeyNames": sorted(
                limited_text(key, 253)
                for key in mapping(resource.get("data"))
                if limited_text(key, 253)
            )[:500],
        }

    if kind == "Service":
        return {
            **common(resource),
            "type": limited_text(
                spec.get("type") or "ClusterIP",
                50,
            ),
            "externalTrafficPolicy": limited_text(
                spec.get("externalTrafficPolicy"),
                50,
            ),
            "sessionAffinity": limited_text(
                spec.get("sessionAffinity"),
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
            "dataSourceKind": limited_text(
                mapping(spec.get("dataSource")).get("kind"),
                100,
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

    if kind == "ServiceAccount":
        return {
            **common(resource),
            "automountServiceAccountToken": resource.get(
                "automountServiceAccountToken"
            ),
            "imagePullSecretCount": len(
                sequence(resource.get("imagePullSecrets"))
            ),
        }

    if kind in {"Role", "ClusterRole"}:
        return {
            **common(resource),
            "rules": [
                {
                    "apiGroups": sorted(
                        limited_text(value, 253)
                        for value in sequence(rule.get("apiGroups"))
                        if limited_text(value, 253)
                    ),
                    "resources": sorted(
                        limited_text(value, 253)
                        for value in sequence(rule.get("resources"))
                        if limited_text(value, 253)
                    ),
                    "verbs": sorted(
                        limited_text(value, 50)
                        for value in sequence(rule.get("verbs"))
                        if limited_text(value, 50)
                    ),
                }
                for rule in sequence(resource.get("rules"))[:500]
                if isinstance(rule, dict)
            ],
        }

    if kind in {"RoleBinding", "ClusterRoleBinding"}:
        role_ref = mapping(resource.get("roleRef"))
        return {
            **common(resource),
            "roleRef": {
                "kind": limited_text(role_ref.get("kind"), 100),
                "name": limited_text(role_ref.get("name"), 253),
            },
            "subjects": [
                {
                    "kind": limited_text(subject.get("kind"), 100),
                    "name": limited_text(subject.get("name"), 253),
                    "namespace": limited_text(
                        subject.get("namespace"),
                        63,
                    ),
                }
                for subject in sequence(resource.get("subjects"))[:500]
                if isinstance(subject, dict)
            ],
        }

    if kind in {
        "MutatingWebhookConfiguration",
        "ValidatingWebhookConfiguration",
    }:
        return {
            **common(resource),
            "webhooks": [
                {
                    "name": limited_text(webhook.get("name"), 253),
                    "failurePolicy": limited_text(
                        webhook.get("failurePolicy"),
                        50,
                    ),
                    "sideEffects": limited_text(
                        webhook.get("sideEffects"),
                        50,
                    ),
                    "admissionReviewVersions": [
                        limited_text(value, 50)
                        for value in sequence(
                            webhook.get("admissionReviewVersions")
                        )
                        if limited_text(value, 50)
                    ][:20],
                    "ruleCount": len(sequence(webhook.get("rules"))),
                }
                for webhook in sequence(resource.get("webhooks"))[:200]
                if isinstance(webhook, dict)
            ],
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
