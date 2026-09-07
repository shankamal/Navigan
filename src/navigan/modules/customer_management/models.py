import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
ProviderCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,49}$")]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Contact(DTO):
    type: Literal["PRIMARY", "TECHNICAL", "BUSINESS", "SECURITY", "ESCALATION"]
    name: Name
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if value is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Invalid email format")
        return value


class ProviderSet(DTO):
    cloudProviders: list[ProviderCode] = Field(max_length=100)

    @field_validator("cloudProviders")
    @classmethod
    def unique(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Duplicate provider codes are not allowed")
        return values


class CreateCustomer(ProviderSet):
    name: Name
    description: Text | None = None
    contacts: list[Contact] = Field(default_factory=list, max_length=100)
    cloudProviders: list[ProviderCode] = Field(default_factory=list, max_length=100)


class UpdateCustomer(DTO):
    name: Name
    description: Text | None = None
    contacts: list[Contact] = Field(default_factory=list, max_length=100)


class Action(DTO):
    reason: Text | None = None
    comments: Text | None = None
