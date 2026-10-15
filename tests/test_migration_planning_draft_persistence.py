"""Isolated service acceptance tests: no AWS, database or connector involved."""
import copy

import pytest

from navigan.modules.migration_management import service as service_module
from navigan.modules.migration_management.service import Service
from navigan.shared.errors import ApiError


class StubAccess:
    user_id = "scope-tester"

    def require(self, privilege):
        assert privilege == "migration.edit"

    def require_customer(self, customer_id, owner_id=None):
        assert customer_id == "CUS-test"


class StubRepo:
    def __init__(self):
        self.current = {
            "migration_id": "MIG-test", "customer_id": "CUS-test",
            "created_by": "creator", "status": "APPROVED", "version": 8,
            "migration_scope": {"namespaces": ["retailflow", "headlamp"]},
            "planning_draft": {"resources": [{"name": "existing"}]},
        }
        self.digest = "a" * 64
        self.saved = []

    def get(self, identifier, lock=False):
        return copy.deepcopy(self.current)

    def get_assessment(self, identifier):
        return {"assessment": {
            "assessmentVersion": 2, "inventoryDigest": self.digest,
            "migrationVersion": 4, "findings": [],
        }}

    def get_source_inventory(self, identifier):
        return {"inventory": {
            "inventoryDigest": self.digest,
            "resources": [{"apiVersion": "apps/v1", "kind": "Deployment",
                           "namespace": "retailflow", "name": "api"}],
        }}

    def require_planning_configuration(self, identifier, version, current):
        assert version == 4

    def save(self, row, old, event, correlation):
        self.current = copy.deepcopy(row)
        self.saved.append(event)


def draft(namespaces, resources=None):
    return {
        "schemaVersion": 1, "mode": "SELECTED_WORKLOADS",
        "assessmentVersion": 2, "inventoryDigest": "a" * 64,
        "selectedNamespaces": namespaces,
        "resources": resources or [], "remediations": [],
        "storageMappings": [], "dataStrategy": "UNDECIDED", "notes": "",
    }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(service_module, "serialize", lambda row: row)
    repo = StubRepo()
    return repo, Service(repo, StubAccess(), "corr-test")


def test_save_and_reload_explicit_namespace_selection(env):
    repo, svc = env
    saved = svc.update("MIG-test", {
        "version": 8, "planningDraft": draft(["retailflow"], [{
            "apiVersion": "apps/v1", "kind": "Deployment", "namespace": "retailflow",
            "name": "api", "treatment": "MIGRATE", "dependency": False,
        }]), "changeReason": "Save selected source scope",
    })
    assert saved["planning_draft"]["selectedNamespaces"] == ["retailflow"]
    assert repo.get("MIG-test")["planning_draft"]["resources"][0]["name"] == "api"
    assert repo.current["migration_scope"]["namespaces"] == ["retailflow", "headlamp"]
    assert repo.saved == ["MIGRATION_PLANNING_UPDATED"]


def test_clear_draft_persists_empty_selection_without_erasing_assessment(env):
    repo, svc = env
    svc.update("MIG-test", {
        "version": 8, "planningDraft": draft([]),
        "changeReason": "Confirmed clear of planning draft",
    })
    assert repo.current["planning_draft"]["resources"] == []
    assert repo.current["planning_draft"]["selectedNamespaces"] == []
    assert repo.current["migration_scope"]["namespaces"] == ["retailflow", "headlamp"]


def test_rejects_outside_scope_without_mutating_approved_migration(env):
    repo, svc = env
    before = copy.deepcopy(repo.current)
    with pytest.raises(ApiError):
        svc.update("MIG-test", {
            "version": 8, "planningDraft": draft(["default"]),
            "changeReason": "Invalid scope expansion",
        })
    assert repo.current == before
    assert repo.saved == []


def test_rejects_stale_version_without_modification(env):
    repo, svc = env
    before = copy.deepcopy(repo.current)
    with pytest.raises(ApiError):
        svc.update("MIG-test", {
            "version": 7, "planningDraft": draft(["retailflow"]),
            "changeReason": "Stale draft save",
        })
    assert repo.current == before
