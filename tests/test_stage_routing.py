"""Regression coverage for HTTP API named-stage paths without database calls."""
import json
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch
from navigan.modules.customer_management import handler
from navigan.shared.auth import Principal
from navigan.shared.errors import ApiError


class StageRoutingTest(unittest.TestCase):
    def event(self, path, stage="v1", method="GET"):
        return {"rawPath": path, "requestContext": {"stage": stage, "http": {"method": method}},
                "queryStringParameters": {"page": "0", "pageSize": "20", "sort": "createdAt,desc"}}

    def test_customer_listing_reaches_service_with_named_stage(self):
        principal = Principal("user", frozenset({"CLOUD_ENGINEER"}), frozenset(), False, True)
        event = self.event("/v1/api/v1/customers")
        with patch.object(handler, "CustomerService") as service, patch.object(handler, "Repository"):
            service.return_value.list.return_value = {"content": [], "totalElements": 0}
            result = handler.execute(event, principal, "test-correlation", tx=lambda: nullcontext(MagicMock()))
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"])["content"], [])
        service.return_value.list.assert_called_once()
        self.assertEqual(event["rawPath"], "/v1/api/v1/customers")

    def test_default_and_already_unprefixed_paths_stay_unchanged(self):
        for stage in ["$default", "v1", None]:
            with self.subTest(stage=stage):
                self.assertEqual(handler.resource_path(self.event("/api/v1/customers", stage)),
                                 "/api/v1/customers")

    def test_detail_and_nested_actions_preserve_resource_suffix(self):
        for suffix in ["/CUS-123", "/CUS-123/review/start", "/CUS-123/cloud-providers"]:
            self.assertEqual(handler.resource_path(self.event("/v1/api/v1/customers" + suffix)),
                             "/api/v1/customers" + suffix)

    def test_different_stage_name_supported(self):
        self.assertEqual(handler.resource_path(self.event("/prod/api/v1/customers", "prod")),
                         "/api/v1/customers")

    def test_wrong_repeated_and_similar_prefixes_are_rejected(self):
        principal = Principal("user", frozenset({"CLOUD_ENGINEER"}), frozenset())
        for path in ["/other/api/v1/customers", "/v1/v1/api/v1/customers", "/v10/api/v1/customers",
                     "/v1/api/v1/customers-extra"]:
            with self.subTest(path=path), self.assertRaises(ApiError) as raised:
                handler.execute(self.event(path), principal, "test")
            self.assertEqual(raised.exception.code, "ROUTE_NOT_FOUND")
