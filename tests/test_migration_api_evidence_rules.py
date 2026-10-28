from navigan.modules.migration_management.api_evidence import evaluate_api_versions

SOURCE = [{"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "apps", "name": "web"}]
SELECTED = {("apps/v1", "Deployment", "apps", "web")}


def test_resource_api_discovery_is_precise_and_still_partial():
    found = evaluate_api_versions(SOURCE, SELECTED, ["apps/v1"], fresh=True,
                                  observed_resources=[{"apiVersion": "apps/v1", "kind": "Deployment"}])
    assert found[0]["status"] == "PARTIAL"
    assert "admission" in found[0]["reason"]


def test_version_alone_is_not_enough_when_kind_discovery_is_available():
    found = evaluate_api_versions(SOURCE, SELECTED, ["apps/v1"], fresh=True,
                                  observed_resources=[{"apiVersion": "apps/v1", "kind": "StatefulSet"}])
    assert found[0]["status"] == "PENDING_EVIDENCE"


def test_stale_evidence_never_verifies_kind():
    found = evaluate_api_versions(SOURCE, SELECTED, ["apps/v1"], fresh=False,
                                  observed_resources=[{"apiVersion": "apps/v1", "kind": "Deployment"}])
    assert found[0]["status"] == "PENDING_EVIDENCE"
