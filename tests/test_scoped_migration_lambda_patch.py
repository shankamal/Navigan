"""Unit tests for the minimum-change DEV migration update."""

import unittest

from scoped_migration_lambda_patch import (
    ALLOWED, BUCKET, ROLE, stage_templates, verify_change_set,
)


class ScopedPreviewTests(unittest.TestCase):
    def test_only_two_lambdas_role_and_install_route_change(self):
        root = {"TemplateBody": {"Resources": {
            "SharedPlatform": {"Type": "AWS::CloudFormation::Stack", "Properties": {"TemplateURL": "untouched"}},
            "MigrationManagement": {"Type": "AWS::CloudFormation::Stack", "Properties": {
                "TemplateURL": f"https://s3.ap-south-1.amazonaws.com/{BUCKET}/old.template",
                "Parameters": {"JwtScope": {"Ref": "JwtScope"}},
            }},
        }}}
        child = {"TemplateBody": {"Resources": {
            "MigrationFunction": {"Type": "AWS::Lambda::Function", "Properties": {
                "Code": {"S3Bucket": BUCKET, "S3Key": "old"},
                "Environment": {"Variables": {"DB_NAME": {"Ref": "DatabaseName"}}},
            }},
            "MigrationConnectorFunction": {"Type": "AWS::Lambda::Function", "Properties": {
                "Code": {"S3Bucket": BUCKET, "S3Key": "old"},
            }},
            "MigrationFunctionRole": {"Type": "AWS::IAM::Role", "Properties": {"Policies": []}},
            "CreateSourceClusterEnrollmentRoute": {"Type": "AWS::ApiGatewayV2::Route", "Properties": {
                "RouteKey": "POST /api/v1/source-clusters/{sourceClusterId}/enrollments",
                "Target": "integrations/abc",
            }},
            "ExistingRoute": {"Type": "AWS::ApiGatewayV2::Route", "Properties": {"RouteKey": "GET /old"}},
        }}}

        url = f"https://s3.ap-south-1.amazonaws.com/{BUCKET}/migration-only/new.json"
        repo = "905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/migration-source-connector"
        digest = "sha256:" + "a" * 64
        key = "navigan-ashok-dev/migration-only/e62378a0e5f1/content-addressed.zip"
        new_root, new_child = stage_templates(root, child, url, key, repo, digest, "api123")
        self.assertEqual(root["TemplateBody"]["Resources"]["SharedPlatform"],
                         new_root["Resources"]["SharedPlatform"])
        self.assertEqual(new_child["Resources"]["ExistingRoute"],
                         child["TemplateBody"]["Resources"]["ExistingRoute"])
        self.assertEqual(new_child["Resources"]["MigrationFunction"]["Properties"]["Environment"]["Variables"]["SOURCE_CONNECTOR_DELIVERY_ROLE_ARN"], ROLE)
        self.assertEqual(new_child["Resources"]["InstallSourceClusterConnectorRoute"]["Properties"]["RouteKey"],
                         "POST /api/v1/source-clusters/{sourceClusterId}/install")

    def test_refuse_replacement_or_broad_nested_changes(self):
        def record(name, action, replacement):
            return {"ResourceChange": {"LogicalResourceId": name, "Action": action,
                                       "Replacement": replacement}}
        okay = {"Status": "CREATE_COMPLETE", "Changes": [
            record(name, "Add" if name == "InstallSourceClusterConnectorRoute" else "Modify", None if name == "InstallSourceClusterConnectorRoute" else "False")
            for name in ALLOWED
        ]}
        verify_change_set(okay)
        okay["Changes"].append(record("CreateMigrationRoute", "Modify", "True"))
        with self.assertRaises(ValueError):
            verify_change_set(okay)


if __name__ == "__main__":
    unittest.main()
