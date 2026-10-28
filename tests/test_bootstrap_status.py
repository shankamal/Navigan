from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from navigan.modules.cluster_management.bootstrap_status import refresh_installer_status
from navigan.modules.cluster_management.connector_installation import ConnectorInstaller


EXECUTION = "NaviganClusterInstaller:11111111-2222-3333-4444-555555555555"


def setup(status="BOOTSTRAPPING"):
    cluster = {
        "cluster_id": "CLU-test", "customer_id": "CUS-test", "status": status,
        "version": 7, "environment_id": "ENV-test", "environment_approved_version": 3,
        "provisioning_role_arn": "arn:aws:iam::123456789012:role/NaviganProvisioningRole",
        "external_id_secret_arn": "external-id-secret",
        "workflow": {"platformBootstrap": {
            "connectorId": "KCC-current", "executionId": EXECUTION, "status": "INSTALLING"
        }},
    }
    repo = MagicMock()
    repo.get.return_value = deepcopy(cluster)
    repo.db.execute.return_value.fetchone.return_value = {
        "connector_id": "KCC-current", "installation_execution_id": EXECUTION,
        "status": "ENROLLED",
    }
    environment = {"configuration": {"location": {"region": "ap-south-1"}}}
    repo.pinned_environment_snapshot.return_value = ({}, environment)
    installer = MagicMock()
    installer.inspect_status.return_value = {"executionId": EXECUTION, "status": "FAILED"}
    return repo, cluster, installer


@pytest.mark.parametrize("status", ["FAILED", "FAULT", "STOPPED", "TIMED_OUT"])
def test_terminal_failure_is_visible_and_audited_without_reinstall(status):
    repo, cluster, installer = setup()
    installer.inspect_status.return_value["status"] = status
    updated = refresh_installer_status(repo, cluster, "request-id", installer)
    assert updated["status"] == "BOOTSTRAP_FAILED"
    assert updated["version"] == 8
    bootstrap = updated["workflow"]["platformBootstrap"]
    assert bootstrap["executionId"] == EXECUTION
    assert bootstrap["status"] == "FAILED"
    assert bootstrap["failureCode"] == "INSTALLER_BUILD_" + status
    repo.save.assert_called_once_with(updated)
    statements = [call.args[0] for call in repo.db.execute.call_args_list]
    assert any("cluster_status_history" in sql for sql in statements)
    assert any("cluster_versions" in sql for sql in statements)
    assert any("cluster_audit_log" in sql for sql in statements)
    installer.start.assert_not_called()


def test_success_still_waits_for_platform_health_and_is_not_polled_twice():
    repo, cluster, installer = setup()
    installer.inspect_status.return_value["status"] = "SUCCEEDED"
    updated = refresh_installer_status(repo, cluster, "request-id", installer)
    assert updated["status"] == "BOOTSTRAPPING"
    assert updated["workflow"]["platformBootstrap"]["installerStatus"] == "SUCCEEDED"
    assert updated["workflow"]["platformBootstrap"]["status"] == "INSTALLING"
    refresh_installer_status(repo, updated, "second-request", installer)
    installer.inspect_status.assert_called_once()
    repo.save.assert_called_once()


@pytest.mark.parametrize("status", ["ACTIVE", "BOOTSTRAP_FAILED", "STOPPED", "DELETING"])
def test_non_bootstrapping_clusters_are_never_polled_or_changed(status):
    repo, cluster, installer = setup(status)
    assert refresh_installer_status(repo, cluster, "request-id", installer) is cluster
    installer.inspect_status.assert_not_called()
    repo.db.execute.assert_not_called()
    repo.save.assert_not_called()


def test_unregistered_or_revoked_connector_cannot_change_cluster():
    repo, cluster, installer = setup()
    repo.db.execute.return_value.fetchone.return_value = None
    refresh_installer_status(repo, cluster, "request-id", installer)
    installer.inspect_status.assert_not_called()
    repo.save.assert_not_called()
    query = repo.db.execute.call_args
    assert "cluster_id=%s AND connector_id=%s AND installation_execution_id=%s" in query.args[0]
    assert query.args[1] == ["CLU-test", "KCC-current", EXECUTION]
    assert "REVOKED" not in query.args[0]


def test_lookup_error_is_not_reported_as_an_installer_failure(caplog):
    repo, cluster, installer = setup()
    installer.inspect_status.side_effect = RuntimeError("secret-token-must-not-be-logged")
    assert refresh_installer_status(repo, cluster, "request-id", installer) is cluster
    repo.save.assert_not_called()
    assert "could not be verified" in caplog.text
    assert "secret-token-must-not-be-logged" not in caplog.text


@pytest.mark.parametrize("change", ["restart", "activated", "revoked"])
def test_build_completion_racing_with_restart_or_activation_is_ignored(change):
    repo, cluster, installer = setup()
    current = deepcopy(cluster)
    if change == "restart":
        current["workflow"]["platformBootstrap"]["executionId"] = "new-execution"
    elif change == "activated":
        current["status"] = "ACTIVE"
    else:
        repo.db.execute.return_value.fetchone.side_effect = [
            {"connector_id": "KCC-current"}, None
        ]
    repo.get.return_value = current
    assert refresh_installer_status(repo, cluster, "request-id", installer) == current
    repo.save.assert_not_called()


@pytest.mark.parametrize("result", [
    {"executionId": EXECUTION, "status": "IN_PROGRESS"},
    {"executionId": "another-build", "status": "FAILED"},
    {"executionId": EXECUTION, "status": "UNKNOWN"},
])
def test_unfinished_or_unverified_builds_do_not_write_status(result):
    repo, cluster, installer = setup()
    installer.inspect_status.return_value = result
    refresh_installer_status(repo, cluster, "request-id", installer)
    repo.save.assert_not_called()
    repo.get.assert_not_called()


def reader():
    repo, cluster, _ = setup()
    sts, secrets, codebuild = MagicMock(), MagicMock(), MagicMock()
    sts.assume_role.return_value = {"Credentials": {
        "AccessKeyId": "access", "SecretAccessKey": "secret", "SessionToken": "session"
    }}
    secrets.get_secret_value.return_value = {"SecretString": "external-id"}
    build = {"id": EXECUTION, "projectName": "NaviganClusterInstaller",
             "arn": "arn:aws:codebuild:ap-south-1:123456789012:build/" + EXECUTION,
             "buildStatus": "FAILED", "environment": {"SECRET": "never-return"}}
    codebuild.batch_get_builds.return_value = {"builds": [build]}
    factory = MagicMock(return_value=codebuild)
    instance = ConnectorInstaller(sts=sts, secrets=secrets, client_factory=factory)
    return instance, cluster, repo.pinned_environment_snapshot.return_value[1], codebuild, build


def test_status_reader_uses_customer_account_and_exact_execution_only():
    installer, cluster, environment, client, _ = reader()
    assert installer.inspect_status(cluster, environment, EXECUTION) == {
        "executionId": EXECUTION, "status": "FAILED"
    }
    client.batch_get_builds.assert_called_once_with(ids=[EXECUTION])
    client.start_build.assert_not_called()
    assert installer.sts.assume_role.call_args.kwargs["RoleArn"] == cluster["provisioning_role_arn"]
    assert installer.client_factory.call_args.kwargs["region_name"] == "ap-south-1"


@pytest.mark.parametrize("field,value", [
    ("id", "other-build"), ("projectName", "OtherInstaller"),
    ("arn", "arn:aws:codebuild:us-east-1:123456789012:build/" + EXECUTION),
    ("arn", "arn:aws:codebuild:ap-south-1:999999999999:build/" + EXECUTION),
    ("buildStatus", "UNKNOWN"),
])
def test_status_reader_rejects_wrong_build_account_region_and_status(field, value):
    installer, cluster, environment, _, build = reader()
    build[field] = value
    with pytest.raises(ValueError):
        installer.inspect_status(cluster, environment, EXECUTION)


def test_status_reader_rejects_unknown_build_and_wrong_project_before_assuming_role():
    installer, cluster, environment, client, _ = reader()
    with pytest.raises(ValueError):
        installer.inspect_status(cluster, environment, EXECUTION.replace("NaviganClusterInstaller", "Diagnostic"))
    installer.sts.assume_role.assert_not_called()
    client.batch_get_builds.return_value = {"builds": [], "buildsNotFound": [EXECUTION]}
    with pytest.raises(ValueError):
        installer.inspect_status(cluster, environment, EXECUTION)


def test_cluster_detail_response_exposes_verified_installer_failure(monkeypatch):
    import json
    from navigan.modules.cluster_management import handler
    from navigan.shared.auth import Principal

    repo, cluster, installer = setup()
    repo.get.return_value = deepcopy(cluster)
    repo.principal = Principal("engineer", frozenset({"CLOUD_ENGINEER"}), frozenset(), True)
    tx = MagicMock()
    monkeypatch.setattr(handler, "transaction", lambda: tx)
    monkeypatch.setattr(handler, "Repository", lambda db, principal: repo)
    evaluator = MagicMock()
    evaluator.evaluate.return_value.has.return_value = True
    monkeypatch.setattr(handler, "AccessEvaluator", lambda db: evaluator)
    monkeypatch.setattr(handler, "refresh_installer_status", lambda r, c, correlation:
                        refresh_installer_status(r, c, correlation, installer))
    event = {"rawPath": "/api/v1/clusters/CLU-test",
             "requestContext": {"http": {"method": "GET"}}}
    response = handler.execute(event, repo.principal, "request-id")
    assert response["statusCode"] == 200
    value = json.loads(response["body"])
    assert value["status"] == "BOOTSTRAP_FAILED"
    assert value["workflow"]["platformBootstrap"]["failureCode"] == "INSTALLER_BUILD_FAILED"
    assert value["workflow"]["platformBootstrap"]["executionId"] == EXECUTION
