import unittest
from unittest.mock import patch
from navigan.modules.migration_management.artifacts import ArtifactRequest, artifact_key, presign_artifact_put
from navigan.modules.migration_management.service import Service
from navigan.shared.errors import ApiError


def request(**overrides):
    fields = dict(customer_id="CUS_1", migration_id="MIG-abc123", assessment_version=2,
                  kind="MANIFEST_YAML", filename="deployment.yaml", sha256="a"*64,
                  size_bytes=100, content_type="application/yaml")
    fields.update(overrides)
    return ArtifactRequest(**fields)


class FakeS3:
    def generate_presigned_url(self, operation, *, Params, ExpiresIn, HttpMethod):
        assert operation == "put_object"
        assert HttpMethod == "PUT"
        assert Params["ServerSideEncryption"] == "aws:kms"
        return "https://example.invalid/upload"


class ArtifactTests(unittest.TestCase):
    def test_upload_intent_is_explicitly_mutating(self):
        try:
            from navigan.modules.migration_management.handler import route_of
        except ModuleNotFoundError as exc:
            if exc.name == "boto3":
                self.skipTest("AWS boto3 dependency is not installed in local test runtime")
            raise
        migration = "/api/v1/migrations/MIG-" + "a" * 32
        self.assertEqual(route_of("POST", migration + "/artifacts/upload-intent")[0], "artifact_upload_intent")

    def test_upload_requires_configured_encrypted_workspace(self):
        class Repo:
            principal = object()

            def get(self, _):
                return {"customer_id": "CUS_1", "planning_draft": {"resources": [{}]}}

            def get_assessment(self, _):
                return {"assessment": {"assessmentVersion": 2}}

        class Access:
            def require(self, permission):
                assert permission == "migration.edit"

        service = Service(Repo(), Access(), "test")
        with patch.dict("os.environ", {"MIGRATION_ARTIFACT_BUCKET": "", "MIGRATION_ARTIFACT_KMS_KEY_ARN": ""}):
            with self.assertRaises(ApiError):
                service.prepare_artifact_upload("MIG-" + "a" * 32, {})

    def test_namespaced_immutable_artifact_path(self):
        result = artifact_key(request())
        self.assertTrue(result.startswith("customers/CUS_1/migrations/MIG-abc123/assessments/v2/"))
        self.assertIn("aaaaaaaaaaaaaaaa-deployment.yaml", result)

    def test_rejects_path_traversal_and_untrusted_kind(self):
        for changed in ({"filename": "../secret"}, {"filename": "a/b.yaml"},
                        {"kind": "SECRET_EXPORT"}, {"size_bytes": 0},
                        {"sha256": "bad"}, {"customer_id": "../other"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                artifact_key(request(**changed))

    def test_presign_requires_kms_and_uses_short_expiry(self):
        with self.assertRaises(ValueError):
            presign_artifact_put(FakeS3(), bucket="artifacts", kms_key_id="", request=request())
        result = presign_artifact_put(FakeS3(), bucket="artifacts", kms_key_id="alias/key", request=request())
        self.assertEqual(result["status"], "UPLOAD_PENDING_VALIDATION")
        self.assertEqual(result["requiredHeaders"]["x-amz-server-side-encryption"], "aws:kms")


if __name__ == "__main__":
    unittest.main()
