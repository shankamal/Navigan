import json
from unittest.mock import MagicMock

from navigan.modules.cluster_management import status_handler


def request(status):
    return {
        "request_id": "KNG-0123456789abcdef0123456789abcdef",
        "cluster_id": "CLU-test",
        "customer_id": "CUS-test",
        "node_group": {
            "name": "checkout-workers",
            "purpose": "APPLICATION",
            "instanceTypes": ["m6i.large", "m6a.large"],
            "capacityType": "ON_DEMAND",
            "minSize": 1,
            "desiredSize": 2,
            "maxSize": 4,
            "diskSizeGiB": 80,
        },
        "status": status,
        "version": 2,
        "plan_artifact_key": "execution/terraform.tfplan",
        "plan_sha256": "a" * 64,
        "execution_artifact_prefix": "execution",
        "workflow": {"currentExecution": {"mode": status.lower()}},
        "cluster_configuration": {
            "nodeGroups": [
                {
                    "name": "system",
                    "purpose": "SYSTEM",
                    "instanceTypes": ["m6i.large"],
                    "capacityType": "ON_DEMAND",
                    "minSize": 2,
                    "desiredSize": 2,
                    "maxSize": 4,
                    "diskSizeGiB": 50,
                }
            ]
        },
        "cluster_version": 8,
        "cluster_status": "ACTIVE",
    }


def test_node_group_plan_completion_records_certified_plan(monkeypatch):
    db = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps(
        {
            "success": True,
            "planSha256": "b" * 64,
            "certification": {"status": "PASSED"},
            "planSummary": {"resourceCount": 1},
            "validation": {"valid": True},
            "securityScan": {"status": "PASSED"},
        }
    ).encode()
    client = MagicMock()
    client.get_object.return_value = {"Body": body}
    monkeypatch.setattr(status_handler, "s3", client)
    monkeypatch.setenv("TERRAFORM_ARTIFACT_BUCKET", "artifacts")

    result = status_handler.handle_node_group_execution(
        db, request("PLAN_RUNNING"), "build-id", "SUCCEEDED", {"id": "event"}
    )

    assert result["status"] == "PLAN_READY"
    update = db.execute.call_args_list[0]
    assert update.args[1][0] == "PLAN_READY"
    assert update.args[1][2] == "b" * 64


def test_node_group_apply_adds_group_without_changing_cluster_status(monkeypatch):
    db = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps(
        {"success": True, "outputs": {"node_groups": {"value": {}}}}
    ).encode()
    client = MagicMock()
    client.get_object.return_value = {"Body": body}
    monkeypatch.setattr(status_handler, "s3", client)
    monkeypatch.setenv("TERRAFORM_ARTIFACT_BUCKET", "artifacts")

    result = status_handler.handle_node_group_execution(
        db, request("APPLYING"), "build-id", "SUCCEEDED", {"id": "event"}
    )

    assert result["status"] == "ACTIVE"
    statements = [call.args[0] for call in db.execute.call_args_list]
    assert any(
        "UPDATE cluster_management.clusters SET configuration=" in sql
        and "status=" not in sql
        for sql in statements
    )
