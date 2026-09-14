from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class CreateEnvironment(Model):
    customerId: str = Field(pattern=r"^CUS-[A-Za-z0-9-]+$", max_length=50)
    cloudProvider: Literal["AWS", "AZURE", "GCP", "OCI"]
    kubernetesDistribution: Literal["EKS", "AKS", "GKE", "OKE"]
    environmentName: str = Field(min_length=1, max_length=150)
    environmentType: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=4000)
    configurationSchemaVersion: str = "1.0"
    configuration: dict[str, Any] = Field(default_factory=dict)


class UpdateEnvironment(Model):
    environmentName: str | None = Field(default=None, min_length=1, max_length=150)
    environmentType: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=4000)
    configurationSchemaVersion: str | None = None
    configuration: dict[str, Any] | None = None
    version: int = Field(gt=0)
    changeReason: str | None = Field(default=None, max_length=2000)


class Action(Model):
    version: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=2000)
    reasonCode: str | None = Field(default=None, max_length=100)
    comments: str | None = Field(default=None, max_length=4000)
    status: Literal["SUSPENDED", "ACTIVE", "DEACTIVATED"] | None = None


class AwsDiscoveryRequest(Model):
    customerId: str = Field(pattern=r"^CUS-[A-Za-z0-9-]+$", max_length=50)
    accountId: str = Field(pattern=r"^[0-9]{12}$")
    roleArn: str = Field(
        pattern=r"^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*NaviganDiscoveryRole$",
        max_length=2048,
    )
    externalId: str = Field(min_length=2, max_length=1224, pattern=r"^[A-Za-z0-9+=,.@:/_-]+$")
    regions: list[str] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def matching_account_and_regions(self):
        if f"::{self.accountId}:role/" not in self.roleArn:
            raise ValueError("Role ARN must belong to the supplied AWS account.")
        if len(set(self.regions)) != len(self.regions) or any(
            not __import__("re").fullmatch(r"^[a-z]{2}(?:-gov)?-[a-z]+-[1-9][0-9]?$", region)
            for region in self.regions
        ):
            raise ValueError("Use distinct valid AWS region codes.")
        return self


class BlueprintReadinessRequest(Model):
    kubernetesDistribution: Literal["EKS", "AKS", "GKE", "OKE"]
    configuration: dict[str, Any]


class CreateBootstrapRemediation(Model):
    customerId: str = Field(pattern=r"^CUS-[A-Za-z0-9-]+$", max_length=50)
    accountId: str = Field(pattern=r"^[0-9]{12}$")
    region: str = Field(pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-[1-9][0-9]?$", max_length=32)
    discoveryRoleArn: str = Field(
        pattern=r"^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*NaviganDiscoveryRole$",
        max_length=2048,
    )
    missingResources: list[
        Literal[
            "EKS_CLUSTER_ROLE", "EKS_NODE_ROLE", "KMS_KEY",
            "PROVISIONING_ROLE", "EXTERNAL_ID_SECRET", "KUBERNETES_VERSIONS",
        ]
    ] = Field(min_length=1, max_length=10)
    requestedActions: list[
        Literal[
            "CREATE_EKS_CLUSTER_ROLE", "CREATE_EKS_NODE_ROLE", "CREATE_KMS_KEY",
            "CREATE_PROVISIONING_ROLE", "REGISTER_EXTERNAL_ID_SECRET",
            "REPAIR_DISCOVERY_PERMISSIONS",
        ]
    ] = Field(min_length=1, max_length=10)
    desiredResources: dict[str, str] = Field(default_factory=dict)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def matching_account(self):
        if f"::{self.accountId}:role/" not in self.discoveryRoleArn:
            raise ValueError("Discovery role ARN must belong to the supplied AWS account.")
        if len(set(self.missingResources)) != len(self.missingResources):
            raise ValueError("Missing resources must be unique.")
        if len(set(self.requestedActions)) != len(self.requestedActions):
            raise ValueError("Requested actions must be unique.")
        allowed = {
            "EKS_CLUSTER_ROLE",
            "EKS_NODE_ROLE",
            "KMS_KEY",
            "PROVISIONING_ROLE",
            "EXTERNAL_ID_SECRET",
        }
        if set(self.desiredResources) - allowed:
            raise ValueError("Unsupported desired resource type.")
        if set(self.desiredResources) - set(self.missingResources):
            raise ValueError("Every desired resource must be included in missing resources.")
        expected_actions = {
            "EKS_CLUSTER_ROLE": "CREATE_EKS_CLUSTER_ROLE",
            "EKS_NODE_ROLE": "CREATE_EKS_NODE_ROLE",
            "KMS_KEY": "CREATE_KMS_KEY",
            "PROVISIONING_ROLE": "CREATE_PROVISIONING_ROLE",
            "EXTERNAL_ID_SECRET": "REGISTER_EXTERNAL_ID_SECRET",
            "KUBERNETES_VERSIONS": "REPAIR_DISCOVERY_PERMISSIONS",
        }
        supplied = dict(zip(self.missingResources, self.requestedActions))
        if len(self.missingResources) != len(self.requestedActions) or any(
            supplied.get(resource) != expected_actions[resource]
            for resource in self.missingResources
        ):
            raise ValueError("Requested actions must correspond to missing resources.")
        import re
        role_name = re.compile(r"^[A-Za-z0-9+=,.@_-]{1,64}$")
        general_name = re.compile(r"^[A-Za-z0-9/_+=.@-]{1,128}$")
        for resource, name in self.desiredResources.items():
            pattern = role_name if resource.endswith("_ROLE") else general_name
            if not pattern.fullmatch(name):
                raise ValueError("Desired resource names contain unsupported characters.")
            if resource == "PROVISIONING_ROLE" and name != "NaviganProvisioningRole":
                raise ValueError("The provisioning role must be named NaviganProvisioningRole.")
        return self


class BootstrapRemediationDecision(Model):
    version: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=2000)


class VerifyBootstrapRemediation(Model):
    version: int = Field(gt=0)
    externalId: str = Field(
        min_length=2,
        max_length=1224,
        pattern=r"^[A-Za-z0-9+=,.@:/_-]+$",
    )
