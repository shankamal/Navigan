from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


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
