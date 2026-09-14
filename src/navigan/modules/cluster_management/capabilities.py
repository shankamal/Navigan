"""Central cluster action resolver.

The frontend renders this contract; it must not infer authorization from roles.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionDefinition:
    code: str
    label: str
    privilege: str
    destructive: bool = False
    confirmation: str | None = None


ACTIONS = {
    "VIEW_DETAILS": ActionDefinition("VIEW_DETAILS", "View details", "cluster.view"),
    "MANAGE": ActionDefinition("MANAGE", "Manage", "cluster.view"),
    "DASHBOARD": ActionDefinition("DASHBOARD", "Dashboard", "cluster.view"),
    "WEB_KUBECTL": ActionDefinition("WEB_KUBECTL", "WebKubectl", "cluster.view"),
    "EDIT_REQUEST": ActionDefinition("EDIT_REQUEST", "Edit request", "cluster.edit"),
    "SUBMIT_REQUEST": ActionDefinition("SUBMIT_REQUEST", "Submit request", "cluster.submit"),
    "START_REVIEW": ActionDefinition("START_REVIEW", "Start review", "cluster.review"),
    "APPROVE": ActionDefinition("APPROVE", "Approve", "cluster.approve"),
    "REJECT": ActionDefinition("REJECT", "Reject", "cluster.approve"),
    "VIEW_PROGRESS": ActionDefinition("VIEW_PROGRESS", "View progress", "cluster.view"),
    "VIEW_LOGS": ActionDefinition("VIEW_LOGS", "View logs", "cluster.logs.view"),
    "APPLY": ActionDefinition(
        "APPLY",
        "Apply approved plan",
        "cluster.apply",
        confirmation="Apply the approved Terraform plan to this cluster?",
    ),
    "STOP": ActionDefinition(
        "STOP",
        "Stop",
        "cluster.apply",
        confirmation="Scale all managed node groups for this cluster to zero?",
    ),
    "START": ActionDefinition(
        "START",
        "Start",
        "cluster.apply",
        confirmation="Restore the approved managed node-group capacity?",
    ),
    "DELETE": ActionDefinition(
        "DELETE",
        "Delete",
        "cluster.decommission",
        destructive=True,
        confirmation="Delete this cluster using its recorded Terraform state?",
    ),
    "RETRY_PROVISIONING": ActionDefinition(
        "RETRY_PROVISIONING", "Retry provisioning", "cluster.retry"
    ),
    "CANCEL_REQUEST": ActionDefinition(
        "CANCEL_REQUEST",
        "Cancel request",
        "cluster.cancel",
        destructive=True,
        confirmation="Cancel this cluster request?",
    ),
    "CANCEL_PROVISIONING": ActionDefinition(
        "CANCEL_PROVISIONING",
        "Cancel provisioning",
        "cluster.cancel",
        destructive=True,
        confirmation="Cancel the active provisioning operation?",
    ),
    "REFRESH_STATUS": ActionDefinition(
        "REFRESH_STATUS", "Refresh status", "cluster.view"
    ),
    "TROUBLESHOOT": ActionDefinition(
        "TROUBLESHOOT", "Troubleshoot", "cluster.logs.view"
    ),
}


STATUS_ACTIONS = {
    "DRAFT": ("VIEW_DETAILS", "EDIT_REQUEST", "SUBMIT_REQUEST", "CANCEL_REQUEST"),
    "REQUESTED": ("VIEW_DETAILS", "EDIT_REQUEST", "CANCEL_REQUEST"),
    "PENDING": ("VIEW_DETAILS", "EDIT_REQUEST", "CANCEL_REQUEST"),
    "SUBMITTED": ("VIEW_DETAILS", "START_REVIEW", "APPROVE", "REJECT"),
    "UNDER_REVIEW": ("VIEW_DETAILS", "APPROVE", "REJECT"),
    "APPROVED": ("VIEW_DETAILS", "VIEW_PROGRESS", "VIEW_LOGS"),
    "PLAN_RUNNING": ("VIEW_PROGRESS", "VIEW_LOGS", "CANCEL_PROVISIONING"),
    "PLAN_READY": ("VIEW_DETAILS", "VIEW_LOGS", "APPLY"),
    "PROVISIONING": ("VIEW_PROGRESS", "VIEW_LOGS", "CANCEL_PROVISIONING"),
    "APPLYING": ("VIEW_PROGRESS", "VIEW_LOGS", "CANCEL_PROVISIONING"),
    "READY": ("DASHBOARD", "WEB_KUBECTL", "MANAGE"),
    "RUNNING": ("DASHBOARD", "WEB_KUBECTL", "MANAGE"),
    "ACTIVE": ("DASHBOARD", "WEB_KUBECTL", "MANAGE", "STOP", "DELETE"),
    "UPDATING": ("VIEW_PROGRESS", "VIEW_LOGS", "MANAGE"),
    "STOPPING": ("VIEW_PROGRESS", "VIEW_LOGS"),
    "STARTING": ("VIEW_PROGRESS", "VIEW_LOGS"),
    "STOPPED": ("START", "MANAGE", "EDIT_REQUEST", "DELETE"),
    "DELETING": ("VIEW_PROGRESS",),
    "DELETED": ("VIEW_DETAILS",),
    "FAILED": (
        "MANAGE",
        "EDIT_REQUEST",
        "VIEW_LOGS",
        "RETRY_PROVISIONING",
        "DELETE",
    ),
    "REJECTED": ("VIEW_DETAILS", "EDIT_REQUEST", "SUBMIT_REQUEST", "CANCEL_REQUEST"),
    "CANCELLED": ("VIEW_DETAILS",),
    "UNKNOWN": ("VIEW_DETAILS", "REFRESH_STATUS", "TROUBLESHOOT"),
    "DISCONNECTED": ("VIEW_DETAILS", "REFRESH_STATUS", "TROUBLESHOOT"),
}


TEMPORARILY_UNAVAILABLE = {
    "DASHBOARD": "Cluster dashboard is not available yet.",
    "WEB_KUBECTL": "WebKubectl requires verified OIDC and Kubernetes RBAC integration.",
    "EDIT_REQUEST": "Only draft or rejected cluster requests can currently be edited.",
    "RETRY_PROVISIONING": "Automated retry is not available for this failure yet.",
    "CANCEL_REQUEST": "Request cancellation is not implemented yet.",
    "CANCEL_PROVISIONING": "The current provider operation cannot be cancelled safely.",
    "REFRESH_STATUS": "Provider status reconciliation is not implemented yet.",
    "TROUBLESHOOT": "Automated troubleshooting is not available yet; review execution logs.",
}


def resolve_cluster_actions(cluster, access):
    """Return state-valid actions filtered by effective backend privileges."""
    status = str(cluster.get("status") or "UNKNOWN").upper()
    actions = []
    for code in STATUS_ACTIONS.get(status, STATUS_ACTIONS["UNKNOWN"]):
        definition = ACTIONS[code]
        if not access.has(definition.privilege):
            continue
        reason = TEMPORARILY_UNAVAILABLE.get(code)
        actions.append(
            {
                "code": definition.code,
                "label": definition.label,
                "enabled": reason is None,
                "disabledReason": reason,
                "destructive": definition.destructive,
                "confirmation": definition.confirmation,
            }
        )
    return actions
