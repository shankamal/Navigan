from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)


class NodeGroup(Model):
    name: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    instanceTypes: list[str] = Field(min_length=1, max_length=10)
    capacityType: Literal["ON_DEMAND", "SPOT"] = "ON_DEMAND"
    desiredSize: int = Field(ge=0, le=1000)
    minSize: int = Field(ge=0, le=1000)
    maxSize: int = Field(ge=1, le=1000)
    diskSizeGiB: int = Field(default=50, ge=20, le=16384)

    @model_validator(mode="after")
    def valid_size(self):
        if not self.minSize <= self.desiredSize <= self.maxSize:
            raise ValueError("Node group size must satisfy min <= desired <= max.")
        return self


class EksConfiguration(Model):
    kubernetesVersion: str = Field(pattern=r"^1\.[0-9]{2}$")
    endpointAccess: Literal["PRIVATE", "PUBLIC_AND_PRIVATE"] = "PRIVATE"
    nodeGroups: list[NodeGroup] = Field(min_length=1, max_length=20)
    tags: dict[str, str] = Field(default_factory=dict)


class Provisioning(Model):
    roleArn: str = Field(
        pattern=r"^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/(?:[A-Za-z0-9+=,.@_-]+/)*NaviganProvisioningRole$",
        max_length=2048,
    )
    externalIdSecretArn: str = Field(
        pattern=r"^arn:(aws|aws-us-gov|aws-cn):secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$",
        max_length=2048,
    )


class CreateCluster(Model):
    environmentId: str = Field(pattern=r"^ENV-[A-Za-z0-9-]+$", max_length=50)
    environmentApprovedVersion: int | None = Field(default=None, gt=0)
    clusterName: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    )


class UpdateCluster(Model):
    clusterName: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
    )
    version: int = Field(gt=0)
    changeReason: str | None = Field(default=None, max_length=2000)


class Action(Model):
    version: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=2000)
    comments: str | None = Field(default=None, max_length=4000)
