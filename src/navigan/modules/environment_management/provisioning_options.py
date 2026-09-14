"""Read-only provisioning references available to a customer cluster request."""

import boto3


def trusted_external_ids(policy_document):
    """Return External IDs enforced by an IAM role trust policy."""
    if not isinstance(policy_document, dict):
        return set()
    statements = policy_document.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    values = set()
    for statement in statements:
        if not isinstance(statement, dict):
            continue
        condition = statement.get("Condition", {})
        if not isinstance(condition, dict):
            continue
        for operator in ("StringEquals", "ForAnyValue:StringEquals"):
            rules = condition.get(operator, {})
            if not isinstance(rules, dict):
                continue
            external_id = rules.get("sts:ExternalId")
            candidates = external_id if isinstance(external_id, list) else [external_id]
            values.update(
                item for item in candidates if isinstance(item, str) and item
            )
    return values


def register_provisioning_external_id(
    customer_id,
    account_id,
    external_id,
    boto3_module=boto3,
):
    """Idempotently register the External ID already enforced by customer IAM."""
    name = f"navigan/provisioning/{customer_id}/{account_id}/external-id"
    client = boto3_module.client("secretsmanager")
    try:
        current = client.get_secret_value(SecretId=name)
    except client.exceptions.ResourceNotFoundException:
        created = client.create_secret(
            Name=name,
            Description=(
                "External ID enforced by the customer NaviganProvisioningRole"
            ),
            SecretString=external_id,
            Tags=[
                {"Key": "ManagedBy", "Value": "Navigan"},
                {"Key": "NaviganCustomerId", "Value": customer_id},
                {"Key": "AwsAccountId", "Value": account_id},
                {"Key": "Purpose", "Value": "ProvisioningExternalId"},
            ],
        )
        return {"name": name, "arn": created["ARN"]}
    if current.get("SecretString") != external_id:
        raise ValueError(
            "The registered provisioning External ID does not match the customer IAM trust policy."
        )
    return {"name": name, "arn": current["ARN"]}


def provisioning_options(customer_id, account_id, boto3_module=boto3):
    prefix = f"navigan/provisioning/{customer_id}/{account_id}/"
    client = boto3_module.client("secretsmanager")
    secrets = []
    paginator = client.get_paginator("list_secrets")
    for page in paginator.paginate(
        Filters=[{"Key": "name", "Values": [prefix]}],
        IncludePlannedDeletion=False,
    ):
        for item in page.get("SecretList", []):
            name, arn = item.get("Name", ""), item.get("ARN", "")
            if name.startswith(prefix) and arn:
                secrets.append({"name": name, "arn": arn})
    return {"provisioningSecrets": sorted(secrets, key=lambda item: item["name"])}
