import unittest
from unittest.mock import MagicMock

from navigan.shared.access import AccessEvaluator, EffectiveAccess, Scope, legacy_access
from navigan.shared.auth import Principal
from navigan.shared.errors import ApiError
from navigan.modules.access_management.handler import execute, serialize


def principal(**changes):
    values = {
        "user_id": "user-1",
        "roles": frozenset({"CLOUD_ENGINEER"}),
        "customer_ids": frozenset({"CUS-one"}),
        "platform_scope": False,
        "can_create": True,
    }
    values.update(changes)
    return Principal(**values)


class AccessEvaluatorTest(unittest.TestCase):
    def test_direct_deny_overrides_role_allow(self):
        repository = MagicMock()
        repository.user.return_value = {
            "user_id": "user-1",
            "display_name": "User One",
            "status": "ACTIVE",
            "authorization_revision": 4,
        }
        repository.privilege_effects.return_value = [
            {"privilege_code": "customer.view", "effect": "ALLOW"},
            {"privilege_code": "customer.view", "effect": "DENY"},
            {"privilege_code": "environment.view", "effect": "ALLOW"},
        ]
        repository.scopes.return_value = [
            {
                "scope_type": "CUSTOMER",
                "customer_id": "CUS-one",
                "resource_type": None,
                "resource_id": None,
            }
        ]

        access = AccessEvaluator(repository).evaluate(principal())

        self.assertFalse(access.has("customer.view"))
        self.assertTrue(access.has("environment.view"))
        self.assertTrue(access.can_access_customer("CUS-one"))
        self.assertFalse(access.can_access_customer("CUS-two"))

    def test_disabled_dynamic_user_is_rejected(self):
        repository = MagicMock()
        repository.user.return_value = {
            "user_id": "user-1",
            "display_name": "User One",
            "status": "DISABLED",
            "authorization_revision": 2,
        }
        with self.assertRaises(ApiError) as raised:
            AccessEvaluator(repository).evaluate(principal())
        self.assertEqual(raised.exception.code, "USER_DISABLED")

    def test_missing_dynamic_user_uses_legacy_claims_during_migration(self):
        repository = MagicMock()
        repository.user.return_value = None

        access = AccessEvaluator(repository).evaluate(principal())

        self.assertEqual(access.source, "LEGACY_CLAIMS")
        self.assertTrue(access.has("customer.create"))
        self.assertTrue(access.can_access_customer("CUS-one"))
        self.assertTrue(access.can_access_customer("CUS-new", owner_id="user-1"))

    def test_platform_scope_allows_all_customers(self):
        access = EffectiveAccess(
            "admin",
            "Administrator",
            1,
            frozenset({"customer.view"}),
            (Scope("PLATFORM"),),
        )
        self.assertTrue(access.can_access_customer("CUS-any"))

    def test_legacy_architect_does_not_receive_create_privileges(self):
        access = legacy_access(
            principal(
                roles=frozenset({"PLATFORM_ARCHITECT"}),
                platform_scope=True,
                can_create=False,
            )
        )
        self.assertTrue(access.has("customer.approve"))
        self.assertFalse(access.has("customer.create"))
        self.assertFalse(access.has("environment.create"))

    def test_access_response_groups_customer_scopes(self):
        access = EffectiveAccess(
            "architect",
            "Platform Architect",
            8,
            frozenset({"customer.view", "customer.review"}),
            (Scope("CUSTOMER", "CUS-two"), Scope("CUSTOMER", "CUS-one")),
        )
        body = serialize(access)
        self.assertEqual(body["authorizationRevision"], 8)
        self.assertEqual(
            body["scopes"],
            [{"type": "CUSTOMER", "customerIds": ["CUS-one", "CUS-two"]}],
        )
        self.assertTrue(body["menuCapabilities"]["canReviewRequests"])

    def test_access_endpoint_rejects_unknown_route(self):
        with self.assertRaises(ApiError) as raised:
            execute(
                {
                    "rawPath": "/api/v1/access/other",
                    "requestContext": {"http": {"method": "GET"}},
                },
                principal(),
                tx=MagicMock(),
            )
        self.assertEqual(raised.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
