"""Trust only API Gateway verified JWT claims, never client identity headers."""

import json
from dataclasses import dataclass
from .errors import ApiError

ROLES = {"CLOUD_ENGINEER", "PLATFORM_ARCHITECT", "SERVICE"}


def claim_list(value):
    if isinstance(value, list):
        result = value
    elif isinstance(value, str):
        try:
            result = json.loads(value) if value.startswith("[") else value.split()
        except ValueError:
            raise ApiError(403, "INVALID_IDENTITY", "Invalid identity claims.") from None
    else:
        result = []
    if not isinstance(result, list) or any(not isinstance(x, str) for x in result):
        raise ApiError(403, "INVALID_IDENTITY", "Invalid identity claims.")
    return frozenset(result)


@dataclass(frozen=True)
class Principal:
    user_id: str
    roles: frozenset[str]
    customer_ids: frozenset[str]
    platform_scope: bool = False
    can_create: bool = False

    @classmethod
    def from_event(cls, event):
        claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub or len(sub) > 100:
            raise ApiError(401, "UNAUTHENTICATED", "A verified access token is required.")
        roles = claim_list(claims.get("roles", [])) & ROLES
        if not roles:
            raise ApiError(403, "FORBIDDEN", "No supported platform role.")
        # Both claims are provisioned only by the trusted identity administrator.
        platform = str(claims.get("platform_scope", "false")).lower() == "true"
        if platform and not roles.intersection({"CLOUD_ENGINEER", "PLATFORM_ARCHITECT"}):
            raise ApiError(403, "FORBIDDEN", "Service identities cannot have platform-wide access.")
        return cls(
            sub,
            roles,
            claim_list(claims.get("customer_ids", [])),
            platform,
            str(claims.get("customer_create", "false")).lower() == "true",
        )

    def require(self, role):
        if role not in self.roles:
            raise ApiError(403, "FORBIDDEN", "This operation is not permitted for your role.")

    def visible(self, customer):
        # Explicit onboarding entitlement gives creators access to their own requests.
        return (
            self.platform_scope
            or customer["customer_id"] in self.customer_ids
            or (self.can_create and "CLOUD_ENGINEER" in self.roles and customer["created_by"] == self.user_id)
        )
