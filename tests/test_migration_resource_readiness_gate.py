
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from navigan.modules.migration_management.service import Service


def assess(empty=False, blocker=False, complete=True):
    now = datetime.now(timezone.utc)

    resource = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "namespace": "retailflow",
        "name": "api",
        "pod": {
            "serviceAccountName": "default",
            "imagePullSecretCount": 0,
            "containers": [],
        },
    }

    digest = "a" * 64

    repo = Mock()
    repo.principal = Mock()

    repo.get.return_value = {
        "target_configuration": {
            "clusterId": "CLU-test"
        },
        "planning_draft": {
            "workflow": "SOURCE_FIRST",
            "assessmentVersion": 1,
            "inventoryDigest": digest,
            "resources": [] if empty else [
                {**resource, "treatment": "MIGRATE"}
            ],
        },
    }

    repo.get_assessment.return_value = {
        "assessment": {
            "assessmentVersion": 1,
            "inventoryDigest": digest,
            "findings": [
                {
                    "severity": "BLOCKER",
                    "disposition": "BLOCKER",
                }
            ] if blocker else [],
        }
    }

    repo.get_target_assessment.return_value = {
        "assessment": {
            "targetClusterId": "CLU-test",
            "assessmentVersion": 1,
            "evidenceLevel": "CONNECTOR_RUNTIME_INVENTORY",
            "snapshot": {
                "observedAt": now.isoformat(),
                "expiresAt": (
                    now + timedelta(minutes=5)
                ).isoformat(),
                "coverageComplete": complete,
                "discoveredApiVersions": ["apps/v1"],
                "discoveredApiResources": [
                    {
                        "apiVersion": "apps/v1",
                        "kind": "Deployment",
                    }
                ],
            },
        }
    }

    repo.get_source_inventory.return_value = {
        "inventory": {"resources": [resource]}
    }

    return Service(
        repo, Mock(), "test"
    ).target_compatibility("MIG-test")


def test_complete_snapshot_cannot_override_pending_resource_checks():
    result = assess()

    assert result["resourceEvaluations"][0]["status"] == "PENDING_EVIDENCE"
    assert result["decision"]["path"] == "PENDING_EVIDENCE"
    assert result["coverageComplete"] is False


def test_empty_scope_cannot_be_direct():
    result = assess(empty=True)

    assert result["decision"]["path"] == "PENDING_EVIDENCE"


def test_source_blocker_is_preserved():
    result = assess(blocker=True)

    assert result["decision"]["path"] == "BLOCKED"


def test_incomplete_target_snapshot_remains_pending():
    result = assess(complete=False)

    assert result["decision"]["path"] == "PENDING_EVIDENCE"
    assert result["coverageComplete"] is False
