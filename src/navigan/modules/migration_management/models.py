from datetime import datetime
from typing import Any, Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


Platform = Literal[
    "SELF_MANAGED_KUBERNETES",
    "EKS",
    "AKS",
    "GKE",
    "ECS",
]

Namespace = Annotated[
    str,
    Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    ),
]

InventoryCount = Annotated[int, Field(ge=0, le=1_000_000)]

SYSTEM_NAMESPACES = {
    "kube-system",
    "kube-public",
    "kube-node-lease",
}


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        strict=True,
        hide_input_in_errors=True,
    )


class SourceCluster(Model):
    platform: Platform
    clusterName: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    distribution: str | None = Field(default=None, max_length=100)
    kubernetesVersion: str | None = Field(
        default=None,
        pattern=r"^1\.[0-9]{2}(?:\.[0-9]+)?$",
    )
    connectorId: str | None = Field(
        default=None,
        pattern=r"^MGC-[A-Za-z0-9-]+$",
        max_length=50,
    )
    accessMode: Literal["READ_ONLY_CONNECTOR"] = "READ_ONLY_CONNECTOR"


class EksTarget(Model):
    platform: Literal["EKS"]
    targetType: Literal[
        "EXISTING_CLUSTER",
        "PLANNED_PLATFORM",
    ] = "EXISTING_CLUSTER"
    environmentId: str = Field(
        pattern=r"^ENV-[A-Za-z0-9-]+$",
        max_length=50,
    )
    environmentApprovedVersion: int = Field(gt=0)
    awsRegion: str | None = Field(
        default=None,
        min_length=3,
        max_length=30,
        pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-[0-9]+$",
    )
    clusterId: str | None = Field(
        default=None,
        pattern=r"^CLU-[A-Za-z0-9-]+$",
        max_length=50,
    )
    clusterName: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    endpointAccess: Literal["PRIVATE", "PUBLIC_AND_PRIVATE"] = "PRIVATE"

    @model_validator(mode="after")
    def target_identity_consistency(self):
        if bool(self.clusterId) != bool(self.clusterName):
            raise ValueError(
                "Existing target cluster ID and name must be supplied together."
            )

        if self.targetType == "PLANNED_PLATFORM" and self.clusterId:
            raise ValueError(
                "A planned target cannot reference an existing cluster."
            )

        return self


class MigrationScope(Model):
    namespaces: list[Namespace] = Field(default_factory=list, max_length=200)
    excludeNamespaces: list[Namespace] = Field(
        default_factory=lambda: sorted(SYSTEM_NAMESPACES),
        max_length=200,
    )
    includeClusterScopedResources: bool = False
    includePersistentData: bool = False

    @model_validator(mode="after")
    def safe_namespace_scope(self):
        selected = set(self.namespaces)
        excluded = set(self.excludeNamespaces)

        protected = selected & SYSTEM_NAMESPACES
        if protected:
            raise ValueError(
                "System namespaces cannot be selected for migration."
            )

        overlap = selected & excluded
        if overlap:
            raise ValueError(
                "A namespace cannot be both selected and excluded."
            )

        return self


class NamespaceCatalogueItem(Model):
    name: Namespace
    resourceCounts: dict[str, InventoryCount] = Field(
        default_factory=dict,
        max_length=50,
    )


class SourceCatalogueReport(Model):
    version: int = Field(gt=0)
    migrationVersion: int = Field(gt=0)
    observedAt: datetime
    sourceKubernetesVersion: str = Field(
        pattern=r"^v?1\.[0-9]{2}(?:\.[0-9]+)?$"
    )
    inventoryDigest: str = Field(pattern=r"^[a-f0-9]{64}$")
    nodeCount: InventoryCount
    architectures: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    namespaces: list[NamespaceCatalogueItem] = Field(
        default_factory=list,
        max_length=200,
    )
    sensitiveDataIncluded: Literal[False] = False

    @field_validator("observedAt", mode="before")
    @classmethod
    def parse_observed_at(cls, value):
        if isinstance(value, str):
            normalized = (
                value[:-1] + "+00:00"
                if value.endswith("Z")
                else value
            )
            try:
                value = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(
                    "observedAt must be a valid ISO-8601 timestamp."
                ) from exc

        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(
                "observedAt must include a timezone."
            )

        return value

    @field_validator("architectures")
    @classmethod
    def validate_architectures(cls, value):
        normalized = sorted(
            {
                item.strip().lower()
                for item in value
                if isinstance(item, str) and item.strip()
            }
        )
        if len(normalized) != len(value):
            raise ValueError(
                "Architectures must be unique non-empty values."
            )
        if any(len(item) > 50 for item in normalized):
            raise ValueError("Architecture value is too long.")
        return normalized

    @model_validator(mode="after")
    def safe_catalogue(self):
        names = [item.name for item in self.namespaces]

        if len(names) != len(set(names)):
            raise ValueError(
                "Each namespace may appear only once."
            )

        protected = set(names) & SYSTEM_NAMESPACES
        if protected:
            raise ValueError(
                "System namespaces cannot be included in source catalogue."
            )

        return self


class CreateMigration(Model):
    customerId: str = Field(
        pattern=r"^CUS-[A-Za-z0-9-]+$",
        max_length=50,
    )
    name: str = Field(min_length=3, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    source: SourceCluster
    target: EksTarget
    scope: MigrationScope = Field(default_factory=MigrationScope)

    @model_validator(mode="after")
    def supported_mvp_path(self):
        if self.source.platform != "SELF_MANAGED_KUBERNETES":
            raise ValueError(
                "The first release supports self-managed Kubernetes "
                "as the source platform."
            )
        return self


class UpdateMigration(Model):
    version: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=3, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    source: SourceCluster | None = None
    target: EksTarget | None = None
    scope: MigrationScope | None = None
    changeReason: str = Field(min_length=3, max_length=2000)


class MigrationAction(Model):
    version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=2000)
    comments: str | None = Field(default=None, max_length=4000)


class DiscoveryAction(MigrationAction):
    connectorToken: str = Field(
        min_length=43,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


SOURCE_INVENTORY_KINDS = {
    "Node",
    "Namespace",
    "Deployment",
    "StatefulSet",
    "DaemonSet",
    "Job",
    "CronJob",
    "Service",
    "Ingress",
    "PersistentVolumeClaim",
    "StorageClass",
    "CustomResourceDefinition",
    "HorizontalPodAutoscaler",
    "PodDisruptionBudget",
    "NetworkPolicy",
}

COMMON_INVENTORY_KEYS = {
    "apiVersion",
    "kind",
    "namespace",
    "name",
    "annotationKeys",
}

SOURCE_INVENTORY_KEYS = {
    "Node": {
        "kubernetesVersion",
        "operatingSystem",
        "architecture",
    },
    "Namespace": set(),
    "Deployment": {"replicas", "pod"},
    "StatefulSet": {"replicas", "pod"},
    "DaemonSet": {"replicas", "pod"},
    "Job": {"replicas", "pod"},
    "CronJob": {"replicas", "pod"},
    "Service": {"type", "selectorKeys", "ports"},
    "Ingress": {
        "ingressClassName",
        "ruleCount",
        "tlsEntryCount",
        "paths",
    },
    "PersistentVolumeClaim": {
        "accessModes",
        "storageClassName",
        "volumeMode",
        "requestedStorage",
    },
    "StorageClass": {
        "provisioner",
        "reclaimPolicy",
        "volumeBindingMode",
    },
    "CustomResourceDefinition": {
        "group",
        "scope",
        "customKind",
        "versions",
    },
    "HorizontalPodAutoscaler": {
        "minReplicas",
        "maxReplicas",
        "targetKind",
    },
    "PodDisruptionBudget": {
        "minAvailable",
        "maxUnavailable",
    },
    "NetworkPolicy": {
        "policyTypes",
        "ingressRuleCount",
        "egressRuleCount",
    },
}

FORBIDDEN_INVENTORY_KEYS = {
    "args",
    "binaryData",
    "command",
    "data",
    "host",
    "hosts",
    "password",
    "path",
    "providerID",
    "secretName",
    "stringData",
    "token",
    "value",
}


def validate_inventory_value(value: Any, depth: int = 0) -> None:
    if depth > 12:
        raise ValueError("Inventory nesting limit exceeded.")

    if isinstance(value, dict):
        if len(value) > 500:
            raise ValueError("Inventory object is too large.")

        for key, nested in value.items():
            if not isinstance(key, str) or len(key) > 253:
                raise ValueError("Inventory object key is invalid.")

            if key.lower() in {
                item.lower()
                for item in FORBIDDEN_INVENTORY_KEYS
            }:
                raise ValueError(
                    f"Sensitive inventory key is forbidden: {key}."
                )

            validate_inventory_value(nested, depth + 1)
        return

    if isinstance(value, list):
        if len(value) > 10_000:
            raise ValueError("Inventory list is too large.")

        for nested in value:
            validate_inventory_value(nested, depth + 1)
        return

    if isinstance(value, str) and len(value) > 4_000:
        raise ValueError("Inventory text value is too long.")

    if value is not None and not isinstance(
        value,
        (str, int, float, bool),
    ):
        raise ValueError("Inventory value type is invalid.")


class SourceInventoryReport(Model):
    schemaVersion: int = Field(gt=0)
    migrationVersion: int = Field(gt=0)
    observedAt: datetime
    sourceKubernetesVersion: str = Field(
        pattern=r"^v?1\.[0-9]{2}(?:\.[0-9]+)?$"
    )
    inventoryDigest: str = Field(pattern=r"^[a-f0-9]{64}$")
    resources: list[dict[str, Any]] = Field(
        min_length=1,
        max_length=25_000,
    )
    sensitiveDataIncluded: Literal[False] = False

    @field_validator("observedAt", mode="before")
    @classmethod
    def parse_observed_at(cls, value):
        if isinstance(value, str):
            normalized = (
                value[:-1] + "+00:00"
                if value.endswith("Z")
                else value
            )
            try:
                value = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(
                    "observedAt must be a valid ISO-8601 timestamp."
                ) from exc

        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(
                "observedAt must include a timezone."
            )

        return value

    @field_validator("resources")
    @classmethod
    def validate_resources(cls, resources):
        seen = set()

        for resource in resources:
            kind = resource.get("kind")
            if kind not in SOURCE_INVENTORY_KINDS:
                raise ValueError(
                    "Unsupported source inventory resource kind."
                )

            allowed = (
                COMMON_INVENTORY_KEYS
                | SOURCE_INVENTORY_KEYS[kind]
            )
            unexpected = set(resource) - allowed
            if unexpected:
                raise ValueError(
                    "Unexpected source inventory fields: "
                    + ", ".join(sorted(unexpected))
                )

            api_version = resource.get("apiVersion")
            if (
                not isinstance(api_version, str)
                or not api_version
                or len(api_version) > 100
            ):
                raise ValueError(
                    "Inventory resource apiVersion is invalid."
                )

            namespace = resource.get("namespace")
            name = resource.get("name")

            if namespace in SYSTEM_NAMESPACES:
                raise ValueError(
                    "System namespaces cannot be assessed."
                )

            if kind == "Namespace":
                if name in SYSTEM_NAMESPACES:
                    raise ValueError(
                        "System namespaces cannot be assessed."
                    )
                if not isinstance(name, str) or not name:
                    raise ValueError(
                        "Namespace inventory requires a name."
                    )

            identity = (
                kind,
                namespace or "",
                name or "",
                resource.get("architecture") or "",
                resource.get("kubernetesVersion") or "",
            )
            if identity in seen:
                raise ValueError(
                    "Duplicate source inventory resource."
                )
            seen.add(identity)

            validate_inventory_value(resource)

        canonical = sorted(
            resources,
            key=lambda item: (
                item.get("kind") or "",
                item.get("namespace") or "",
                item.get("name") or "",
            ),
        )
        if resources != canonical:
            raise ValueError(
                "Source inventory resources must be canonically sorted."
            )

        return resources

    @model_validator(mode="after")
    def verify_inventory_digest(self):
        import hashlib
        import json

        payload = {
            "schemaVersion": self.schemaVersion,
            "sensitiveDataIncluded": False,
            "resources": self.resources,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

        if len(encoded) > 8 * 1024 * 1024:
            raise ValueError(
                "Source inventory payload exceeds the size limit."
            )

        calculated = hashlib.sha256(encoded).hexdigest()
        if calculated != self.inventoryDigest:
            raise ValueError(
                "Source inventory digest validation failed."
            )

        return self


class AssessmentFinding(Model):
    code: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )
    severity: Literal["INFO", "WARNING", "BLOCKER"]
    disposition: Literal[
        "SEAMLESS",
        "AUTOMATED_CHANGE",
        "MANUAL_CHANGE",
        "BLOCKER",
    ] = "MANUAL_CHANGE"
    category: Literal[
        "KUBERNETES_API",
        "WORKLOAD",
        "NETWORK",
        "IDENTITY",
        "STORAGE",
        "SECURITY",
        "OBSERVABILITY",
    ]
    namespace: Namespace | None = None
    resourceKind: str | None = Field(default=None, max_length=100)
    resourceName: str | None = Field(default=None, max_length=253)
    message: str = Field(min_length=1, max_length=4000)
    remediation: str | None = Field(default=None, max_length=4000)


class AssessmentReport(Model):
    version: int = Field(gt=0)
    migrationVersion: int = Field(gt=0)
    observedAt: datetime

    @field_validator("observedAt", mode="before")
    @classmethod
    def parse_observed_at(cls, value):
        if isinstance(value, str):
            normalized = (
                value[:-1] + "+00:00"
                if value.endswith("Z")
                else value
            )
            try:
                value = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(
                    "observedAt must be a valid ISO-8601 timestamp."
                ) from exc

        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(
                "observedAt must include a timezone."
            )

        return value
    sourceKubernetesVersion: str = Field(
        pattern=r"^1\.[0-9]{2}(?:\.[0-9]+)?$"
    )
    inventoryDigest: str = Field(pattern=r"^[a-f0-9]{64}$")
    compatibilityScore: int = Field(ge=0, le=100)
    inventorySummary: dict[str, InventoryCount] = Field(max_length=100)
    findings: list[AssessmentFinding] = Field(max_length=5000)
    sensitiveDataIncluded: Literal[False] = False

    @model_validator(mode="after")
    def blocker_consistency(self):
        has_blocker = any(
            finding.severity == "BLOCKER"
            for finding in self.findings
        )
        if has_blocker and self.compatibilityScore == 100:
            raise ValueError(
                "An assessment with blockers cannot score 100."
            )
        return self
