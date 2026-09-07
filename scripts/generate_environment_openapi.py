"""Generate the Environment module contract independently from Customer Management."""

import json
from pathlib import Path
from navigan.modules.environment_management.models import CreateEnvironment, UpdateEnvironment, Action
from navigan.modules.environment_management.service import TRANSITIONS
from navigan.modules.environment_management.configuration import schema

root = Path(__file__).resolve().parents[1]
components = {
    m.__name__: m.model_json_schema(ref_template="#/components/schemas/{model}")
    for m in [CreateEnvironment, UpdateEnvironment, Action]
}
for dist in ["EKS", "AKS", "GKE", "OKE"]:
    components[dist + "Configuration"] = schema(dist, "1.0")
components["Error"] = {
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message", "details", "correlationId"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"},
                "correlationId": {"type": "string"},
            },
        }
    },
}
components["Environment"] = {
    "type": "object",
    "required": [
        "environmentId",
        "customerId",
        "customerName",
        "cloudProvider",
        "kubernetesDistribution",
        "environmentName",
        "environmentType",
        "status",
        "version",
        "configuration",
        "configurationSchemaVersion",
        "createdAt",
        "createdBy",
        "workflow",
    ],
    "properties": {
        **components["CreateEnvironment"]["properties"],
        "environmentId": {"type": "string"},
        "customerName": {"type": "string"},
        "status": {
            "type": "string",
            "enum": [
                "DRAFT",
                "SUBMITTED",
                "UNDER_REVIEW",
                "APPROVED",
                "REJECTED",
                "ACTIVE",
                "SUSPENDED",
                "DEACTIVATED",
            ],
        },
        "version": {"type": "integer"},
        "approvedVersion": {"type": ["integer", "null"]},
        "workflow": {"type": "object"},
        "createdBy": {"type": "string"},
        "createdAt": {"type": "string", "format": "date-time"},
        "updatedAt": {"type": ["string", "null"], "format": "date-time"},
    },
}
components["Page"] = {
    "type": "object",
    "required": ["items", "pagination"],
    "properties": {
        "items": {"type": "array", "items": {"type": "object"}},
        "pagination": {
            "type": "object",
            "required": ["page", "pageSize", "totalElements", "totalPages"],
            "properties": {
                k: {"type": "integer", "minimum": 0}
                for k in ["page", "pageSize", "totalElements", "totalPages"]
            },
        },
    },
}
paths = {}
operations = [
    ("post", "", "CreateEnvironment"),
    ("get", "", None),
    ("get", "/{environmentId}", None),
    ("put", "/{environmentId}", "UpdateEnvironment"),
    ("get", "/metadata", None),
    ("get", "/configuration-schemas/{distribution}/{schemaVersion}", None),
    ("patch", "/{environmentId}/status", "Action"),
]
operations += [("post", "/{environmentId}/" + a, "Action") for a in TRANSITIONS]
operations += [
    ("get", "/{environmentId}/" + a, None)
    for a in ["versions", "versions/{version}", "status-history", "reviews", "audit-log"]
]
import re

for method, suffix, model in operations:
    path = "/api/v1/environments" + suffix
    params = [
        {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}
        for name in re.findall(r"{(\w+)}", path)
    ]
    if model:
        params += [
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "maxLength": 128},
            }
        ]
        if model != "CreateEnvironment":
            params += [
                {
                    "name": "If-Match",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Optional when body.version is supplied; both must agree.",
                }
            ]
    elif method == "get" and (
        not suffix or suffix.endswith(("versions", "status-history", "reviews", "audit-log"))
    ):
        for name in ["page", "pageSize"]:
            params.append(
                {
                    "name": name,
                    "in": "query",
                    "schema": {
                        "type": "integer",
                        "minimum": 0 if name == "page" else 1,
                        "maximum": 1000000 if name == "page" else 100,
                        "default": 0 if name == "page" else 20,
                    },
                }
            )
        if not suffix:
            params += [
                {"name": n, "in": "query", "schema": {"type": "string"}}
                for n in [
                    "customerId",
                    "customerName",
                    "cloudProvider",
                    "kubernetesDistribution",
                    "environmentName",
                    "environmentType",
                    "status",
                    "region",
                    "createdBy",
                    "createdFrom",
                    "createdTo",
                    "search",
                    "sort",
                ]
            ]
    success = "201" if model == "CreateEnvironment" else "200"
    output = (
        {"$ref": "#/components/schemas/Environment"}
        if model or suffix == "/{environmentId}" or suffix.endswith("/{version}")
        else {"$ref": "#/components/schemas/Page"}
        if not suffix or suffix.endswith(("versions", "status-history", "reviews", "audit-log"))
        else {"type": "object"}
    )
    op = {
        "operationId": method + "Environment" + "".join(w.title() for w in re.findall(r"\w+", suffix)),
        "summary": (
            "Create environment"
            if not suffix and model
            else "List environments"
            if not suffix
            else method.upper() + " " + suffix
        ),
        "security": [{"Cognito": ["navigan/api"]}],
        "parameters": params,
        "responses": {
            success: {"description": "Success", "content": {"application/json": {"schema": output}}},
            **{
                str(s): {
                    "description": t,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                }
                for s, t in [
                    (400, "Invalid request"),
                    (401, "Unauthenticated"),
                    (403, "Forbidden"),
                    (404, "Not found"),
                    (409, "Conflict"),
                    (422, "Configuration validation failed"),
                    (500, "Internal failure with correlation ID"),
                ]
            },
        },
    }
    if model:
        op["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/" + model}}},
        }
    paths.setdefault(path, {})[method] = op
out = {
    "openapi": "3.1.0",
    "info": {
        "title": "Navigan Environment Management",
        "version": "1.1.0",
        "description": "Provider-specific infrastructure baselines, governance and immutable version history. No cloud provisioning.",
    },
    "servers": [{"url": "https://q0i8bcekw1.execute-api.ap-south-1.amazonaws.com/v1"}],
    "paths": paths,
    "components": {
        "schemas": components,
        "securitySchemes": {
            "Cognito": {
                "type": "oauth2",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": "https://YOUR_COGNITO_DOMAIN/oauth2/authorize",
                        "tokenUrl": "https://YOUR_COGNITO_DOMAIN/oauth2/token",
                        "scopes": {"navigan/api": "Platform API access"},
                    }
                },
            }
        },
    },
}
(root / "docs/environment-openapi.json").write_text(json.dumps(out, indent=2) + "\n")
