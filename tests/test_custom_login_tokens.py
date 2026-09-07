"""Verify privilege boundaries of the inline Cognito token function without AWS calls."""
import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml


class CustomLoginTokensTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = yaml.load((Path(__file__).parents[1] / "infrastructure/auth/template.yaml").read_text(), Loader=yaml.BaseLoader)
        code = template["Resources"]["TokenFunction"]["Properties"]["Code"]["ZipFile"]
        namespace = {}
        exec(compile(code, "token_function", "exec"), namespace)
        cls.handler = staticmethod(namespace["handler"])

    def run_token(self, groups=(), client="publicclient", version="2", **request):
        event = {"version": version, "callerContext": {"clientId": client},
                 "request": {"groupConfiguration": {"groupsToOverride": list(groups)}, **request}, "response": {}}
        with patch.dict(os.environ, APP_CLIENT_ID="publicclient", API_SCOPE="navigan/api"):
            return self.handler(copy.deepcopy(event), None)

    def access(self, **kwargs):
        return self.run_token(**kwargs)["response"]["claimsAndScopeOverrideDetails"]["accessTokenGeneration"]

    def test_unassigned_users_and_spoofed_attributes_get_no_privileges(self):
        access = self.access(groups=["navigan/naviganadmin", "NAVIGAN_PLATFORM_SCOPE"],
                             userAttributes={"custom:roles": "PLATFORM_ARCHITECT"},
                             clientMetadata={"roles": "PLATFORM_ARCHITECT"})
        self.assertEqual(access["scopesToAdd"], [])
        self.assertEqual(json.loads(access["claimsToAddOrOverride"]["roles"]), [])
        self.assertFalse(access["claimsToAddOrOverride"]["platform_scope"])

    def test_engineer_customer_scope_requires_explicit_entitlements(self):
        access = self.access(groups=["NAVIGAN_CLOUD_ENGINEER", "NAVIGAN_CUSTOMER_CUS-123", "NAVIGAN_CUSTOMER_CREATOR"])
        self.assertEqual(access["scopesToAdd"], ["navigan/api"])
        claims = access["claimsToAddOrOverride"]
        self.assertEqual(json.loads(claims["customer_ids"]), ["CUS-123"])
        self.assertTrue(claims["customer_create"])
        self.assertFalse(claims["platform_scope"])

    def test_architect_does_not_gain_create_entitlement(self):
        claims = self.access(groups=["NAVIGAN_PLATFORM_ARCHITECT", "NAVIGAN_PLATFORM_SCOPE", "NAVIGAN_CUSTOMER_CREATOR"])["claimsToAddOrOverride"]
        self.assertEqual(json.loads(claims["roles"]), ["PLATFORM_ARCHITECT"])
        self.assertTrue(claims["platform_scope"])
        self.assertFalse(claims["customer_create"])

    def test_other_clients_untouched(self):
        self.assertEqual(self.run_token(client="other")["response"], {})

    def test_v1_fails_closed(self):
        with self.assertRaises(ValueError):
            self.run_token(version="1")

    def test_revoked_membership_removes_scope_on_refresh(self):
        access = self.access(groups=[])
        self.assertEqual(access["scopesToSuppress"], ["navigan/api"])
        self.assertEqual(json.loads(access["claimsToAddOrOverride"]["customer_ids"]), [])

    def test_token_claims_work_with_backend_after_gateway_text_conversion(self):
        from navigan.shared.auth import Principal
        access = self.access(groups=["NAVIGAN_CLOUD_ENGINEER", "NAVIGAN_CUSTOMER_CREATOR"])
        claims = access["claimsToAddOrOverride"]
        self.assertIsInstance(claims["roles"], str)
        self.assertIsInstance(claims["customer_ids"], str)
        # JWT-authorized Lambda event claims are text; string claims keep their JSON encoding.
        forwarded = {key: value if isinstance(value, str) else json.dumps(value)
                     for key, value in claims.items()}
        forwarded["sub"] = "test-user"
        principal = Principal.from_event({"requestContext": {"authorizer": {"jwt": {"claims": forwarded}}}})
        principal.require("CLOUD_ENGINEER")
        self.assertTrue(principal.can_create)
        self.assertFalse(principal.platform_scope)
        self.assertTrue(principal.visible({"customer_id": "CUS-own", "created_by": "test-user"}))
        self.assertFalse(principal.visible({"customer_id": "CUS-other", "created_by": "another-user"}))

    def test_customer_assignment_survives_text_boundary(self):
        from navigan.shared.auth import Principal
        claims = self.access(groups=["NAVIGAN_CLOUD_ENGINEER", "NAVIGAN_CUSTOMER_CUS-123"])["claimsToAddOrOverride"]
        claims["sub"] = "test-user"
        principal = Principal.from_event({"requestContext": {"authorizer": {"jwt": {"claims": claims}}}})
        self.assertEqual(principal.customer_ids, frozenset({"CUS-123"}))
        self.assertFalse(principal.can_create)

    def test_malformed_claims_are_still_rejected(self):
        from navigan.shared.auth import claim_list
        from navigan.shared.errors import ApiError
        for malformed in ["[CLOUD_ENGINEER]", '["CLOUD_ENGINEER", 1]']:
            with self.subTest(value=malformed), self.assertRaises(ApiError):
                claim_list(malformed)
