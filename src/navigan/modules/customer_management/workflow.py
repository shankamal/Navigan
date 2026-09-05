from navigan.shared.errors import ApiError

# action: (permitted source states, destination, role, audit action, event type)
TRANSITIONS = {
    "submit": (
        {"DRAFT", "REJECTED"},
        "SUBMITTED",
        "CLOUD_ENGINEER",
        "CUSTOMER_SUBMITTED",
        "CustomerSubmitted",
    ),
    "resubmit": ({"REJECTED"}, "SUBMITTED", "CLOUD_ENGINEER", "CUSTOMER_SUBMITTED", "CustomerSubmitted"),
    "review/start": (
        {"SUBMITTED"},
        "UNDER_REVIEW",
        "PLATFORM_ARCHITECT",
        "CUSTOMER_REVIEW_STARTED",
        "CustomerReviewStarted",
    ),
    "approve": ({"UNDER_REVIEW"}, "APPROVED", "PLATFORM_ARCHITECT", "CUSTOMER_APPROVED", "CustomerApproved"),
    "reject": ({"UNDER_REVIEW"}, "REJECTED", "PLATFORM_ARCHITECT", "CUSTOMER_REJECTED", "CustomerRejected"),
    "activate": ({"APPROVED"}, "ACTIVE", "PLATFORM_ARCHITECT", "CUSTOMER_ACTIVATED", "CustomerActivated"),
    "suspend": ({"ACTIVE"}, "SUSPENDED", "PLATFORM_ARCHITECT", "CUSTOMER_SUSPENDED", "CustomerSuspended"),
    "reactivate": (
        {"SUSPENDED"},
        "ACTIVE",
        "PLATFORM_ARCHITECT",
        "CUSTOMER_REACTIVATED",
        "CustomerReactivated",
    ),
    "deactivate": (
        {"ACTIVE"},
        "DEACTIVATED",
        "PLATFORM_ARCHITECT",
        "CUSTOMER_DEACTIVATED",
        "CustomerDeactivated",
    ),
}
STATUSES = {
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "ACTIVE",
    "SUSPENDED",
    "DEACTIVATED",
}


def check_transition(customer, action, principal, body):
    sources, target, role, audit, event = TRANSITIONS[action]
    principal.require(role)
    if customer["status"] not in sources:
        raise ApiError(
            422,
            "INVALID_STATUS_TRANSITION",
            "Action is not allowed in the current state.",
            {"currentStatus": customer["status"], "action": action},
        )
    if action in {"review/start", "approve", "reject"} and principal.user_id in {
        customer["created_by"],
        customer.get("submitted_by"),
    }:
        raise ApiError(
            403, "SELF_REVIEW_FORBIDDEN", "An independent Platform Architect must review the request."
        )
    if action in {"reject", "suspend", "deactivate"} and not body.get("reason"):
        raise ApiError(422, "REASON_REQUIRED", "A non-empty reason is required.")
    return target, audit, event


def check_edit(customer, principal):
    principal.require("CLOUD_ENGINEER")
    if customer["status"] not in {"DRAFT", "REJECTED"}:
        raise ApiError(
            422, "INVALID_CUSTOMER_EDIT_STATE", "Customer data is editable only in DRAFT or REJECTED."
        )


def check_version(customer, expected):
    if customer["version"] != expected:
        raise ApiError(
            409, "CONCURRENT_UPDATE", "The customer has changed. Fetch it and retry with its version."
        )
