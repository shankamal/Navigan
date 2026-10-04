from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class NodeGroup(Model):
    name: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    purpose: Literal["SYSTEM", "APPLICATION"] = "SYSTEM"
    instanceTypes: list[str] = Field(min_length=1, max_length=10)
    capacityType: Literal["ON_DEMAND", "SPOT"] = "ON_DEMAND"
    desiredSize: int = Field(ge=0, le=1000)
    minSize: int = Field(ge=0, le=1000)
    maxSize: int = Field(ge=1, le=1000)
    diskSizeGiB: int = Field(default=50, ge=20, le=16384)
    managementMode: Literal["MANAGED", "ADOPTED"] = "MANAGED"

    @model_validator(mode="after")
    def valid_size(self):
        if not self.minSize <= self.desiredSize <= self.maxSize:
            raise ValueError("Node group size must satisfy min <= desired <= max.")
        return self


class Provisioning(Model):
    roleArn: str = Field(
        pattern=r"^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*NaviganProvisioningRole$",
        max_length=2048,
    )
    externalIdSecretArn: str = Field(
        pattern=r"^arn:(aws|aws-us-gov|aws-cn):secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$",
        max_length=2048,
    )


class ClusterBlueprint(Model):
    name: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    kubernetesVersion: str = Field(pattern=r"^1\.[0-9]{2}$")
    endpointAccess: Literal["PRIVATE", "PUBLIC_AND_PRIVATE"] = "PRIVATE"
    nodeGroups: list[NodeGroup] = Field(min_length=1, max_length=20)
    tags: dict[str, str] = Field(default_factory=dict)
    provisioning: Provisioning


class CreateCluster(Model):
    environmentId: str = Field(pattern=r"^ENV-[A-Za-z0-9-]+$", max_length=50)
    environmentApprovedVersion: int | None = Field(default=None, gt=0)
    blueprintName: str = Field(min_length=1, max_length=63)
    clusterName: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    )
    kubernetesVersion: str = Field(pattern=r"^1\.[0-9]{2}$")
    endpointAccess: Literal["PRIVATE", "PUBLIC_AND_PRIVATE"] = "PRIVATE"
    nodeGroups: list[NodeGroup] = Field(min_length=1, max_length=20)
    provisioningRoleArn: str = Field(
        pattern=r"^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*NaviganProvisioningRole$",
        max_length=2048,
    )
    externalIdSecretArn: str = Field(
        pattern=r"^arn:(aws|aws-us-gov|aws-cn):secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$",
        max_length=2048,
    )
    tags: dict[str, str] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=4000)
    githubOrganization: str = Field(
        min_length=1,
        max_length=39,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$",
    )

    @model_validator(mode="after")
    def initial_cluster_has_one_system_pool(self):
        if len(self.nodeGroups) != 1 or self.nodeGroups[0].purpose != "SYSTEM":
            raise ValueError(
                "A new cluster must start with exactly one system node group."
            )
        if self.nodeGroups[0].capacityType != "ON_DEMAND":
            raise ValueError("The system node group must use on-demand capacity.")
        if self.nodeGroups[0].minSize < 2 or self.nodeGroups[0].desiredSize < 2:
            raise ValueError("The system node group must keep at least two nodes ready.")
        if any(
            instance_type.endswith((".nano", ".micro"))
            for instance_type in self.nodeGroups[0].instanceTypes
        ):
            raise ValueError(
                "The EKS system node group cannot use nano or micro instance types."
            )
        return self


class GitHubAuthorizationRequest(Model):
    version: int = Field(gt=0)


class CompleteGitHubAuthorization(Model):
    version: int = Field(gt=0)
    state: str = Field(min_length=32, max_length=256)
    installationId: int = Field(gt=0)


class UpdateCluster(Model):
    clusterName: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    )
    description: str | None = Field(default=None, max_length=4000)
    version: int = Field(gt=0)
    changeReason: str | None = Field(default=None, max_length=2000)


class Action(Model):
    version: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=2000)
    comments: str | None = Field(default=None, max_length=4000)


class SystemNodeGroupMigration(Model):
    version: int = Field(gt=0)
    targetNodeGroup: NodeGroup
    legacyNodeGroupName: str = Field(
        pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
    )
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def valid_migration(self):
        if self.targetNodeGroup.purpose != "SYSTEM":
            raise ValueError("The adopted default node group must have SYSTEM purpose.")
        if self.targetNodeGroup.managementMode != "ADOPTED":
            raise ValueError("The existing default node group must use ADOPTED management mode.")
        if self.targetNodeGroup.name == self.legacyNodeGroupName:
            raise ValueError("The target and legacy node groups must be different.")
        if self.targetNodeGroup.capacityType != "ON_DEMAND":
            raise ValueError("The system node group must use on-demand capacity.")
        if (
            self.targetNodeGroup.minSize < 2
            or self.targetNodeGroup.desiredSize < 2
        ):
            raise ValueError("The system node group must keep at least two nodes ready.")
        return self


class KubernetesAccessAssignment(Model):
    subjectType: Literal["USER", "GROUP"]
    subjectId: str = Field(
        min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/+_-]*$"
    )
    profileCode: Literal[
        "NAMESPACE_VIEWER", "NAMESPACE_OPERATOR", "CLUSTER_OPERATOR"
    ]
    namespace: str | None = Field(
        default=None,
        max_length=253,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    reason: str = Field(min_length=3, max_length=2000)


class RevokeKubernetesAccess(Model):
    reason: str = Field(min_length=3, max_length=2000)


class ConnectorInstallationRequest(Model):
    version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=2000)


class ToolSessionRequest(Model):
    toolCode: Literal[
        "HEADLAMP", "GRAFANA", "PROMETHEUS", "ARGOCD", "WEBKUBECTL"
    ]


class CreateNodeGroupRequest(Model):
    nodeGroup: NodeGroup
    reason: str = Field(min_length=3, max_length=2000)

    @model_validator(mode="after")
    def application_node_group_only(self):
        if self.nodeGroup.purpose != "APPLICATION":
            raise ValueError("Additional node groups must have APPLICATION purpose.")
        return self


class NodeGroupRequestAction(Model):
    version: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=2000)
    comments: str | None = Field(default=None, max_length=4000)
