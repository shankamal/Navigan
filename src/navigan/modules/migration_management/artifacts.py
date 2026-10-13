"""Tenant-scoped artifact storage primitives for migration planning.

This module does not execute workloads, export live secrets or promote container
images. API handlers must first authorize the migration and its customer.
"""
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import quote

ALLOWED_KINDS = {"MANIFEST_YAML", "HELM_CHART", "HELM_VALUES", "VALIDATION_REPORT"}
CONTENT_TYPES = {
    "MANIFEST_YAML": {"application/yaml", "text/yaml", "text/plain"},
    "HELM_CHART": {"application/gzip", "application/x-gzip"},
    "HELM_VALUES": {"application/yaml", "text/yaml", "text/plain"},
    "VALIDATION_REPORT": {"application/json"},
}
MAX_SIZE = 20 * 1024 * 1024
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class ArtifactRequest:
    customer_id: str
    migration_id: str
    assessment_version: int
    kind: str
    filename: str
    sha256: str
    size_bytes: int
    content_type: str


def artifact_key(request: ArtifactRequest) -> str:
    for label, value in (("customer_id", request.customer_id), ("migration_id", request.migration_id)):
        if not SAFE_ID.fullmatch(value):
            raise ValueError(f"Invalid {label}")
    if request.assessment_version < 1:
        raise ValueError("Assessment version must be positive")
    if request.kind not in ALLOWED_KINDS:
        raise ValueError("Unsupported artifact kind")
    if request.content_type not in CONTENT_TYPES[request.kind]:
        raise ValueError("Unsupported artifact media type")
    if not 0 < request.size_bytes <= MAX_SIZE:
        raise ValueError("Artifact size is outside permitted range")
    if not SHA256.fullmatch(request.sha256):
        raise ValueError("Invalid SHA-256 digest")
    if not request.filename or len(request.filename) > 180 or request.filename in {".", ".."}:
        raise ValueError("Invalid filename")
    if "/" in request.filename or "\\" in request.filename or any(ord(c) < 32 for c in request.filename):
        raise ValueError("Artifact filename must be a single safe component")
    safe_name = quote(request.filename, safe="._-")
    return (f"customers/{request.customer_id}/migrations/{request.migration_id}/"
            f"assessments/v{request.assessment_version}/{request.kind.lower()}/"
            f"{request.sha256[:16]}-{safe_name}")


def presign_artifact_put(s3_client, *, bucket: str, kms_key_id: str, request: ArtifactRequest, expires_in: int = 600) -> dict:
    """Create a tightly scoped upload URL. Caller must authenticate/authorize first.

    A trusted server must verify the uploaded object's digest and content before
    marking its record validated; a presigned upload alone is never confirmation.
    """
    if not bucket or not kms_key_id:
        raise ValueError("S3 bucket and KMS key are required")
    if not 60 <= expires_in <= 900:
        raise ValueError("Upload expiry out of range")
    key = artifact_key(request)
    params = {
        "Bucket": bucket,
        "Key": key,
        "ContentType": request.content_type,
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": kms_key_id,
        "Metadata": {"expected-sha256": request.sha256, "artifact-kind": request.kind},
    }
    url = s3_client.generate_presigned_url("put_object", Params=params, ExpiresIn=expires_in, HttpMethod="PUT")
    return {"method": "PUT", "url": url, "key": key, "expiresInSeconds": expires_in,
            "requiredHeaders": {"Content-Type": request.content_type,
                                "x-amz-server-side-encryption": "aws:kms",
                                "x-amz-server-side-encryption-aws-kms-key-id": kms_key_id,
                                "x-amz-meta-expected-sha256": request.sha256,
                                "x-amz-meta-artifact-kind": request.kind},
            "status": "UPLOAD_PENDING_VALIDATION"}
