"""Exercise version discovery through its HTTP handler, including query validation."""
import json
from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from navigan.modules.cluster_management import handler, utility_upgrades
from navigan.modules.cluster_management.upgrade_plans import utcnow
from navigan.shared.errors import ApiError


@pytest.mark.parametrize("utility", ["headlamp", "Headlamp"])
def test_utility_options_accepts_frontend_query_and_returns_verified_targets(monkeypatch, utility):
    repo = MagicMock()
    repo.platform_components.return_value = {"components": [{
        "componentCode": "headlamp", "version": "0.45.0", "status": "READY",
        "syncStatus": "Synced", "observedAt": utcnow().isoformat(),
    }]}
    monkeypatch.setattr(handler, "transaction", lambda: nullcontext(MagicMock()))
    monkeypatch.setattr(handler, "Repository", lambda *_: repo)
    monkeypatch.setattr(handler, "AccessEvaluator", lambda *_: MagicMock())
    monkeypatch.setattr(utility_upgrades, "upstream_releases", lambda _: ["0.46.0", "0.45.0"])
    event = {
        "rawPath": handler.BASE + "/CLU-test/utility-upgrade-options",
        "requestContext": {"http": {"method": "GET"}},
        "queryStringParameters": {"utility": utility},
    }
    result = handler.execute(event, MagicMock(), "test-query")
    body = json.loads(result["body"])
    assert result["statusCode"] == 200
    assert body["versions"] == ["0.46.0"]
    assert body["releaseStatus"] == "UPDATE_AVAILABLE"
    assert body["blockReason"] is None
    repo.get.assert_called_with("CLU-test")


@pytest.mark.parametrize("params,allow_utility", [
    ({"utility": "headlamp"}, False),
    ({"utility": "headlamp", "upstreamUrl": "https://untrusted.test"}, True),
])
def test_unknown_queries_remain_rejected(params, allow_utility):
    with pytest.raises(ApiError, match="Unknown query parameter"):
        handler.query_of({"queryStringParameters": params}, allow_utility=allow_utility)


def test_list_query_pagination_still_validates():
    assert handler.query_of({"queryStringParameters": {"pageSize": "10"}})["pageSize"] == 10
    with pytest.raises(ApiError, match="Check pagination"):
        handler.query_of({"queryStringParameters": {"pageSize": "101"}})
