from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from navigan.modules.migration_management.service import Service
from navigan.modules.migration_management.models import InstallSourceConnector
from navigan.shared.errors import ApiError

SOURCE = "SRC-" + "a" * 32
MIGRATION = "MIG-" + "b" * 32


class Access:
    def __init__(self, customers=("CUS-db", "CUS-demo")):
        self.customers = customers

    def require(self, privilege):
        assert privilege == "migration.edit"

    def require_customer(self, customer, owner=None):
        if customer not in self.customers:
            raise ApiError(403, "FORBIDDEN", "Not permitted")


@pytest.fixture
def setup():
    source = {
        "source_cluster_id": SOURCE,
        "customer_id": "CUS-db",
        "created_by": "creator",
        "status": "CONNECTED",
        "version": 2,
        "location_type": "CLOUD",
        "cloud_provider": "AWS",
        "delivery_method": "AWS_SSM",
        "delivery_configuration": {
            "accountId": "123456789012",
            "region": "ap-south-1",
            "managedInstanceId": "i-0123456789abcdef0",
            "kubeconfigPath": "/etc/kubernetes/admin.conf",
        },
        "connector_last_seen_at": datetime.now(timezone.utc) - timedelta(days=1),
    }
    repo = MagicMock()
    repo.principal = SimpleNamespace(user_id="creator")
    repo.get_source_cluster.return_value = source
    repo.get.return_value = {
        "customer_id": "CUS-db",
        "created_by": "creator",
        "status": "DISCOVERY_PENDING",
        "source_configuration": {"sourceClusterId": SOURCE},
    }
    repo.source_installation_conflicts.return_value = []
    repo.create_source_enrollment.return_value = {"enrollment_id": "SCE-test"}
    installer = MagicMock()
    installer.start.return_value = {
        "commandId": "command-1",
        "managedInstanceId": "i-0123456789abcdef0",
        "status": "INSTALLATION_STARTED",
    }
    return Service(repo, Access(), "recovery-test"), repo, source, installer


def body():
    return {"version": 2, "reason": "Restore existing source connection", "recoveryMigrationId": MIGRATION}


def conflict(**changes):
    return {
        "source_cluster_id": "SRC-other",
        "customer_id": "CUS-demo",
        "created_by": "creator",
        "customer_name": "Demo customer",
        "has_active_assignment": False,
        **changes,
    }


def test_recovery_reuses_existing_registration_and_does_not_modify_migration(setup):
    service, repo, source, installer = setup
    repo.source_installation_conflicts.return_value = [conflict()]
    check = service.source_installation_check(source)
    assert check["canRestore"] is True
    assert check["conflicts"] == []
    assert check["code"] == "SOURCE_SCOPED_INSTALL_AVAILABLE"
    result = service.install_source_connector(SOURCE, body(), installer)
    assert result["sourceClusterId"] == SOURCE
    repo.lock_source_installation.assert_called_once_with(source)
    installer.start.assert_called_once()
    repo.create_source_cluster.assert_not_called()
    repo.save.assert_not_called()


def test_other_customer_does_not_block_isolated_installation_or_leak_metadata(setup):
    service, repo, source, installer = setup
    service.access = Access(("CUS-db",))
    repo.source_installation_conflicts.return_value = [conflict(customer_name="Private customer", has_active_assignment=True)]
    check = service.source_installation_check(source)
    assert check["canRestore"] is True
    assert check["conflicts"] == []
    assert "Private customer" not in str(check)
    service.install_source_connector(SOURCE, body(), installer)
    repo.source_installation_conflicts.assert_not_called()
    installer.start.assert_called_once()
    repo.save.assert_not_called()


def test_installation_of_a_source_outside_customer_access_is_still_denied(setup):
    service, repo, source, installer = setup
    service.access = Access(("CUS-demo",))
    assert service.source_installation_check(source)["canRestore"] is False
    with pytest.raises(ApiError) as error:
        service.install_source_connector(SOURCE, body(), installer)
    assert error.value.code == "FORBIDDEN"
    repo.create_source_enrollment.assert_not_called()
    installer.start.assert_not_called()


def test_fresh_heartbeat_does_not_trigger_reinstall(setup):
    service, repo, source, installer = setup
    source["connector_last_seen_at"] = datetime.now(timezone.utc)
    with pytest.raises(ApiError) as error:
        service.install_source_connector(SOURCE, body(), installer)
    assert error.value.code == "ALREADY_CONNECTED"
    repo.source_installation_conflicts.assert_not_called()
    installer.start.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"customer_id": "CUS-demo"},
        {"source_configuration": {"sourceClusterId": "SRC-other"}},
        {"status": "ASSESSMENT_READY"},
        {"status": "DISCOVERING"},
    ],
)
def test_changed_association_or_completed_assessment_blocks_recovery(setup, change):
    service, repo, source, installer = setup
    repo.get.return_value.update(change)
    with pytest.raises(ApiError):
        service.install_source_connector(SOURCE, body(), installer)
    installer.start.assert_not_called()


def test_optimistic_source_version_checked_before_recovery(setup):
    service, repo, source, installer = setup
    source["version"] = 3
    with pytest.raises(ApiError) as error:
        service.install_source_connector(SOURCE, body(), installer)
    assert error.value.code == "CONCURRENT_UPDATE"
    repo.lock_source_installation.assert_not_called()
    installer.start.assert_not_called()


def test_install_schema_accepts_valid_recovery_context_and_rejects_invalid_id():
    assert InstallSourceConnector.model_validate(body()).recoveryMigrationId == MIGRATION
    with pytest.raises(ValueError):
        InstallSourceConnector.model_validate({**body(), "recoveryMigrationId": "other"})


def test_existing_source_get_route_returns_recovery_check_without_new_gateway_route(setup, monkeypatch):
    import json
    from contextlib import nullcontext
    from navigan.modules.migration_management import handler

    _, repo, _, _ = setup
    access = MagicMock()
    monkeypatch.setattr(handler, "transaction", lambda: nullcontext(object()))
    monkeypatch.setattr(handler, "Repository", lambda db, principal: repo)
    monkeypatch.setattr(handler, "AccessRepository", MagicMock())
    evaluator = MagicMock()
    evaluator.evaluate.return_value = access
    monkeypatch.setattr(handler, "AccessEvaluator", lambda _: evaluator)
    result = handler.execute(
        {
            "rawPath": f"/api/v1/source-clusters/{SOURCE}",
            "requestContext": {"http": {"method": "GET"}},
            "queryStringParameters": {"installationCheck": "true"},
        },
        repo.principal,
        "check-test",
    )
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["installationCheck"]["canRestore"] is True
    repo.create_source_enrollment.assert_not_called()


@pytest.mark.parametrize("pending", [False, True])
def test_another_registrations_install_or_assessment_cannot_block_isolated_resources(setup, pending):
    service, repo, source, installer = setup
    repo.source_installation_conflicts.return_value = [conflict(installation_in_progress=pending, has_active_assignment=True)]
    service.install_source_connector(SOURCE, {"version": 2, "reason": "New connector install"}, installer)
    repo.lock_source_installation.assert_called_once_with(source)
    repo.source_installation_conflicts.assert_not_called()
    installer.start.assert_called_once_with(source, repo.create_source_enrollment.call_args.args[1])
    repo.save.assert_not_called()


def test_normal_install_also_reuses_a_live_connector_instead_of_rotating_it(setup):
    service, repo, source, installer = setup
    source["connector_last_seen_at"] = datetime.now(timezone.utc)
    with pytest.raises(ApiError) as error:
        service.install_source_connector(SOURCE, {"version": 2, "reason": "Install connector"}, installer)
    assert error.value.code == "ALREADY_CONNECTED"
    installer.start.assert_not_called()
    repo.create_source_enrollment.assert_not_called()


def test_recovery_can_start_from_an_existing_assessment_draft(setup):
    service, repo, source, installer = setup
    repo.get.return_value["status"] = "DRAFT"
    service.install_source_connector(SOURCE, body(), installer)
    installer.start.assert_called_once()
    repo.save.assert_not_called()
