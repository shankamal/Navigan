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
