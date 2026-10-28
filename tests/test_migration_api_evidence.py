from navigan.modules.migration_management.api_evidence import evaluate_api_versions


SOURCE = [{"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "retailflow", "name": "api"}]
SELECTED = {("apps/v1", "Deployment", "retailflow", "api")}


def test_observed_group_version_is_partial_only():
    result = evaluate_api_versions(SOURCE, SELECTED, ["apps/v1"], fresh=True)
    assert result[0]["status"] == "PARTIAL"
    assert "kind availability" in result[0]["reason"]


def test_missing_version_or_stale_evidence_is_pending():
    assert evaluate_api_versions(SOURCE, SELECTED, ["v1"], fresh=True)[0]["status"] == "PENDING_EVIDENCE"
    assert evaluate_api_versions(SOURCE, SELECTED, ["apps/v1"], fresh=False)[0]["status"] == "PENDING_EVIDENCE"


def test_unselected_resources_excluded():
    assert evaluate_api_versions(SOURCE, set(), ["apps/v1"], fresh=True) == []
