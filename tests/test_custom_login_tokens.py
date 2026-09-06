"""Verify privilege boundaries of the inline Cognito token function without AWS calls."""
import copy
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
        self.assertEqual(access["claimsToAddOrOverride"]["roles"], [])
        self.assertFalse(access["claimsToAddOrOverride"]["platform_scope"])

    def test_engineer_customer_scope_requires_explicit_entitlements(self):
        access = self.access(groups=["NAVIGAN_CLOUD_ENGINEER", "NAVIGAN_CUSTOMER_CUS-123", "NAVIGAN_CUSTOMER_CREATOR"])
        self.assertEqual(access["scopesToAdd"], ["navigan/api"])
        claims = access["claimsToAddOrOverride"]
        self.assertEqual(claims["customer_ids"], ["CUS-123"])
        self.assertTrue(claims["customer_create"])
        self.assertFalse(claims["platform_scope"])

    def test_architect_does_not_gain_create_entitlement(self):
        claims = self.access(groups=["NAVIGAN_PLATFORM_ARCHITECT", "NAVIGAN_PLATFORM_SCOPE", "NAVIGAN_CUSTOMER_CREATOR"])["claimsToAddOrOverride"]
        self.assertEqual(claims["roles"], ["PLATFORM_ARCHITECT"])
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
        self.assertEqual(access["claimsToAddOrOverride"]["customer_ids"], [])
