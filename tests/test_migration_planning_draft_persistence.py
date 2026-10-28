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
        self.principal = type("Principal", (), {"user_id": "scope-tester"})()
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

    def require_planning_configuration(self, identifier, version, current, source_only=False):
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


def source_first_inventory(repo, monkeypatch, resources=None, assessment_mode="SOURCE_ONLY"):
    repo.current["migration_scope"] = {"namespaces": []}
    monkeypatch.setenv("MIGRATION_SOURCE_FIRST_ENABLED", "true")
    original = repo.get_assessment("MIG-test")
    original["assessment"]["inventorySummary"] = {"assessmentMode": assessment_mode}
    monkeypatch.setattr(repo, "get_assessment", lambda _: copy.deepcopy(original))
    if resources is not None:
        monkeypatch.setattr(repo, "get_source_inventory", lambda _: {"inventory": {
            "inventoryDigest": repo.digest, "resources": resources
        }})


def test_source_first_accepts_assessed_namespace_missing_from_registration_scope(env, monkeypatch):
    repo, svc = env
    source_first_inventory(repo, monkeypatch)
    saved = svc.update("MIG-test", {
        "version": 8, "planningDraft": {**draft(["retailflow"]), "workflow": "SOURCE_FIRST"},
        "changeReason": "Select assessed source namespace",
    })
    assert saved["planning_draft"]["selectedNamespaces"] == ["retailflow"]
    assert saved["migration_scope"]["namespaces"] == []


def test_source_first_accepts_empty_namespace_present_in_inventory(env, monkeypatch):
    repo, svc = env
    source_first_inventory(repo, monkeypatch, [{"apiVersion": "v1", "kind": "Namespace", "name": "empty-app"}])
    saved = svc.update("MIG-test", {
        "version": 8, "planningDraft": {**draft(["empty-app"]), "workflow": "SOURCE_FIRST"},
        "changeReason": "Select assessed empty namespace",
    })
    assert saved["planning_draft"]["selectedNamespaces"] == ["empty-app"]


def test_source_first_rejects_namespace_absent_from_inventory_even_if_in_preset_scope(env, monkeypatch):
    repo, svc = env
    source_first_inventory(repo, monkeypatch)
    repo.current["migration_scope"] = {"namespaces": ["unassessed"]}
    before = copy.deepcopy(repo.current)
    with pytest.raises(ApiError) as error:
        svc.update("MIG-test", {
            "version": 8, "planningDraft": {**draft(["unassessed"]), "workflow": "SOURCE_FIRST"},
            "changeReason": "Reject unassessed namespace",
        })
    assert error.value.code == "NAMESPACE_OUTSIDE_ASSESSMENT"
    assert repo.current == before
    assert repo.saved == []


@pytest.mark.parametrize("workflow,mode,enabled", [
    ("SOURCE_FIRST", "TARGET_BOUND", "true"),
    (None, "SOURCE_ONLY", "true"),
    ("SOURCE_FIRST", "SOURCE_ONLY", "false"),
])
def test_inventory_scope_does_not_expand_legacy_or_disabled_workflows(env, monkeypatch, workflow, mode, enabled):
    repo, svc = env
    source_first_inventory(repo, monkeypatch, assessment_mode=mode)
    monkeypatch.setenv("MIGRATION_SOURCE_FIRST_ENABLED", enabled)
    planning = draft(["retailflow"])
    if workflow:
        planning["workflow"] = workflow
    with pytest.raises(ApiError):
        svc.update("MIG-test", {"version": 8, "planningDraft": planning, "changeReason": "Preserve assessment boundary"})
    assert repo.saved == []


def test_source_first_stale_digest_still_rejected_before_namespace_selection(env, monkeypatch):
    repo, svc = env
    source_first_inventory(repo, monkeypatch)
    planning = {**draft(["retailflow"]), "workflow": "SOURCE_FIRST", "inventoryDigest": "b" * 64}
    with pytest.raises(ApiError) as error:
        svc.update("MIG-test", {"version": 8, "planningDraft": planning, "changeReason": "Stale inventory"})
    assert error.value.code == "PLANNING_EVIDENCE_CHANGED"
    assert repo.saved == []
