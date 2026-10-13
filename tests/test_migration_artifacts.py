import unittest
from navigan.modules.migration_management.artifacts import ArtifactRequest, artifact_key, presign_artifact_put


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
