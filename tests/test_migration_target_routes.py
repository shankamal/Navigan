from navigan.modules.migration_management.handler import route_of

BASE = "/api/v1/migrations/MIG-" + "a" * 32


def test_target_assessment_api_routes():
    assert route_of("GET", BASE + "/target-assessment")[0] == "target_assessment_get"
    assert route_of("POST", BASE + "/target-assessment")[0] == "target_assessment_run"


def test_target_assessment_rejects_other_methods():
    import pytest
    from navigan.shared.errors import ApiError
    with pytest.raises(ApiError):
        route_of("DELETE", BASE + "/target-assessment")
