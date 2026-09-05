"""Generate the checked-in contract from validated request DTOs and route definitions."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from navigan.modules.customer_management.models import (
    Action,
    Contact,
    CreateCustomer,
    ProviderSet,
    UpdateCustomer,
)
from navigan.modules.customer_management.workflow import TRANSITIONS, STATUSES


def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def prop(type_="string", **kwargs):
    return {"type": type_, **kwargs}


def build():
    schemas = {}
    for model in [Action, Contact, CreateCustomer, ProviderSet, UpdateCustomer]:
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[model.__name__] = schema
    customer_props = {
        "customerId": prop(),
        "onboardingRequestId": prop(),
        "name": prop(),
        "description": {"type": ["string", "null"]},
        "status": prop(enum=sorted(STATUSES)),
        "version": prop("integer", minimum=1),
        "reviewCycle": prop("integer"),
        "cloudProviders": prop("array", items=prop()),
        "contacts": prop("array", items=ref("Contact")),
    }
    for prefix in [
        "created",
        "updated",
        "submitted",
        "approved",
        "rejected",
        "activated",
        "suspended",
        "reactivated",
        "deactivated",
    ]:
        customer_props[prefix + "By"] = {"type": ["string", "null"]}
        customer_props[prefix + "At"] = {"type": ["string", "null"], "format": "date-time"}
    for reason in ["rejectionReason", "suspensionReason", "deactivationReason"]:
        customer_props[reason] = {"type": ["string", "null"]}
    schemas["Customer"] = {
        "type": "object",
        "properties": customer_props,
        "required": [
            "customerId",
            "onboardingRequestId",
            "name",
            "status",
            "version",
            "cloudProviders",
            "contacts",
        ],
    }
    schemas["Pagination"] = {
        "type": "object",
        "properties": {
            k: prop("integer", minimum=0) for k in ["page", "pageSize", "totalElements", "totalPages"]
        },
    }
    schemas["CustomerSummary"] = {
        "type": "object",
        "properties": {
            k: customer_props[k]
            for k in ["customerId", "name", "status", "version", "createdAt", "updatedAt", "cloudProviders"]
        },
    }
    schemas["CustomerList"] = {
        "type": "object",
        "properties": {"items": prop("array", items=ref("CustomerSummary")), "pagination": ref("Pagination")},
    }
    schemas["CustomerProviders"] = {
        "type": "object",
        "properties": {
            "customerId": prop(),
            "version": prop("integer"),
            "cloudProviders": prop("array", items=prop()),
        },
    }
    history = {
        "historyId": prop("integer"),
        "customerId": prop(),
        "fromStatus": {"type": ["string", "null"]},
        "toStatus": prop(),
        "changedBy": prop(),
        "changedAt": prop(format="date-time"),
        "reason": {"type": ["string", "null"]},
        "comments": {"type": ["string", "null"]},
        "correlationId": prop(),
    }
    schemas["StatusHistory"] = {
        "type": "object",
        "properties": {
            "customerId": prop(),
            "history": prop("array", items={"type": "object", "properties": history}),
            "pagination": ref("Pagination"),
        },
    }
    schemas["AuditRecord"] = {
        "type": "object",
        "properties": {
            "auditId": prop("integer"),
            "customerId": prop(),
            "action": prop(),
            "performedBy": prop(),
            "performedAt": prop(format="date-time"),
            "source": prop(),
            "correlationId": prop(),
            "oldValue": {},
            "newValue": {},
        },
    }
    schemas["Review"] = {
        "type": "object",
        "properties": {
            "reviewId": prop(),
            "customerId": prop(),
            "reviewCycle": prop("integer"),
            "reviewerId": prop(),
            "reviewStatus": prop(),
            "reviewedAt": prop(format="date-time"),
            "comments": {"type": ["string", "null"]},
            "rejectionReason": {"type": ["string", "null"]},
        },
    }
    for name, item in [("AuditLog", "AuditRecord"), ("Reviews", "Review")]:
        schemas[name] = {
            "type": "object",
            "properties": {
                "customerId": prop(),
                "items": prop("array", items=ref(item)),
                "pagination": ref("Pagination"),
            },
        }
    schemas["Error"] = {
        "type": "object",
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "required": ["code", "message", "details", "correlationId"],
                "properties": {
                    "code": prop(),
                    "message": prop(),
                    "details": prop("object"),
                    "correlationId": prop(),
                },
            }
        },
    }
    paths = {}

    def endpoint(path, method, summary, output="Customer", request=None, created=False):
        parameters = [{"name": "X-Correlation-ID", "in": "header", "schema": prop(maxLength=100)}]
        if "{customerId}" in path:
            parameters.append({"name": "customerId", "in": "path", "required": True, "schema": prop()})
        if method in {"post", "put"}:
            parameters.append(
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "schema": prop(minLength=1, maxLength=128),
                    "description": "Actor and operation scoped. Replay the same body AND If-Match value. Keys retained until an explicit administrative retention policy.",
                }
            )
            if "{customerId}" in path:
                parameters.append(
                    {
                        "name": "If-Match",
                        "in": "header",
                        "required": True,
                        "schema": prop(),
                        "description": "Current positive integer version, bare or quoted. Required for all mutations of an existing customer.",
                    }
                )
        if output in {"CustomerList", "StatusHistory", "AuditLog", "Reviews"}:
            parameters.extend(
                [
                    {
                        "name": "page",
                        "in": "query",
                        "schema": prop("integer", minimum=0, maximum=1000000, default=0),
                    },
                    {
                        "name": "pageSize",
                        "in": "query",
                        "schema": prop("integer", minimum=1, maximum=100, default=20),
                    },
                ]
            )
        if output == "CustomerList":
            for name in ["search", "status", "cloudProvider", "createdBy", "sort"]:
                parameters.append(
                    {
                        "name": name,
                        "in": "query",
                        "schema": prop(),
                        "description": "name/createdAt/updatedAt/status,asc/desc" if name == "sort" else name,
                    }
                )
        responses = {
            str(201 if created else 200): {
                "description": "Success",
                "headers": {
                    "X-Correlation-ID": {"schema": prop()},
                    "ETag": {"schema": prop(), "description": "Present on responses containing a version."},
                },
                "content": {"application/json": {"schema": ref(output)}},
            }
        }
        for status, description in [
            (400, "Invalid input"),
            (401, "Unauthenticated"),
            (403, "Forbidden"),
            (404, "Not found or outside customer scope"),
            (405, "Unsupported method"),
            (409, "Duplicate, idempotency or concurrency conflict"),
            (422, "Business validation or lifecycle failure"),
            (500, "Internal error"),
        ]:
            responses[str(status)] = {
                "description": description,
                "content": {"application/json": {"schema": ref("Error")}},
            }
        operation = {
            "summary": summary,
            "operationId": summary.replace(" ", ""),
            "tags": ["Customer Management"],
            "parameters": parameters,
            "responses": responses,
        }
        if request:
            operation["requestBody"] = {
                "required": request != "Action",
                "content": {"application/json": {"schema": ref(request)}},
            }
        paths.setdefault(path, {})[method] = operation

    base = "/api/v1/customers"
    endpoint(base, "post", "Create Customer", request="CreateCustomer", created=True)
    endpoint(base, "get", "List Customers", output="CustomerList")
    endpoint(base + "/{customerId}", "get", "Get Customer")
    endpoint(base + "/{customerId}", "put", "Update Customer", request="UpdateCustomer")
    endpoint(
        base + "/{customerId}/cloud-providers", "get", "Get Customer Providers", output="CustomerProviders"
    )
    endpoint(
        base + "/{customerId}/cloud-providers", "put", "Replace Customer Providers", request="ProviderSet"
    )
    for action in TRANSITIONS:
        endpoint(
            base + "/{customerId}/" + action,
            "post",
            action.replace("/", " ").title() + " Customer",
            request="Action",
        )
    for action, schema in [
        ("status-history", "StatusHistory"),
        ("audit-log", "AuditLog"),
        ("reviews", "Reviews"),
    ]:
        endpoint(base + "/{customerId}/" + action, "get", "Get " + schema, output=schema)
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Navigan Customer Management",
            "version": "1.0.0",
            "description": "Customer Management specification v2.0 implemented for Lambda. See implementation-decisions.md for resolved policies. Request JWT must contain the configured API access scope.",
        },
        "servers": [
            {
                "url": "https://{apiId}.execute-api.{region}.amazonaws.com/v1",
                "variables": {"apiId": {"default": "replace-me"}, "region": {"default": "ap-south-1"}},
            }
        ],
        "security": [{"BearerAuth": []}],
        "paths": paths,
        "components": {
            "securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
            "schemas": schemas,
        },
    }


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "docs/openapi.json"
    path.write_text(json.dumps(build(), indent=2) + "\n")
    print(path)
