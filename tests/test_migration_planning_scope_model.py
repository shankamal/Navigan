"""Planning namespace persistence is additive and backwards-compatible."""
import pytest
from pydantic import ValidationError

from navigan.modules.migration_management.models import MigrationPlanningDraft


BASE = {
    "schemaVersion": 1,
    "mode": "SELECTED_WORKLOADS",
    "assessmentVersion": 2,
    "inventoryDigest": "a" * 64,
    "resources": [],
    "remediations": [],
    "dataStrategy": "UNDECIDED",
    "notes": "",
}


def test_legacy_draft_without_namespace_field_still_parses():
    model = MigrationPlanningDraft.model_validate(BASE)
    assert model.selectedNamespaces is None


def test_explicit_empty_namespace_selection_persists():
    model = MigrationPlanningDraft.model_validate({**BASE, "selectedNamespaces": []})
    assert model.model_dump()["selectedNamespaces"] == []


def test_multiple_namespace_selection_persists():
    model = MigrationPlanningDraft.model_validate(
        {**BASE, "selectedNamespaces": ["headlamp", "retailflow"]}
    )
    assert model.selectedNamespaces == ["headlamp", "retailflow"]


def test_duplicate_namespace_selection_is_rejected():
    with pytest.raises(ValidationError, match="Selected namespaces must be unique"):
        MigrationPlanningDraft.model_validate(
            {**BASE, "selectedNamespaces": ["retailflow", "retailflow"]}
        )
