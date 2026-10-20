import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from navigan.modules.migration_management.artifact_recovery import recover, storage_key, public_job
from navigan.modules.migration_management.deployment_sources import AnalyzeDeploymentSources
from navigan.modules.migration_management.recovery_worker import validate_oci
from navigan.shared.errors import ApiError


def archive(tmp_path, *, corrupt=False, absent=False):
    config = b'{"architecture":"amd64","os":"linux"}'
    cd = hashlib.sha256(config).hexdigest()
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:" + cd,
                "size": len(config),
            },
            "layers": [],
        }
    ).encode()
    md = hashlib.sha256(manifest).hexdigest()
    index = json.dumps(
        {
            "schemaVersion": 2,
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": "sha256:" + md,
                    "size": len(manifest),
                }
            ],
        }
    ).encode()
    path = tmp_path / "image.tar"
    with tarfile.open(path, "w") as handle:
        values = {"index.json": index, "blobs/sha256/" + md: manifest}
        if not absent:
            values["blobs/sha256/" + cd] = b"x" * len(config) if corrupt else config
        for name, data in values.items():
            item = tarfile.TarInfo(name)
            item.size = len(data)
            handle.addfile(item, io.BytesIO(data))
    return path, "sha256:" + md


def test_oci_verifies_content_and_expected_digest(tmp_path):
    path, digest = archive(tmp_path)
    assert validate_oci(path, digest) == 2
    with pytest.raises(ValueError, match="EXPECTED_IMAGE_NOT_EXPORTED"):
        validate_oci(path, "sha256:" + "f" * 64)


@pytest.mark.parametrize(
    "options,reason", [({"corrupt": True}, "DIGEST_MISMATCH"), ({"absent": True}, "INCOMPLETE_ARCHIVE")]
)
def test_oci_missing_or_corrupt_blob_never_recovered(tmp_path, options, reason):
    path, digest = archive(tmp_path, **options)
    with pytest.raises(ValueError, match=reason):
        validate_oci(path, digest)


def test_recovery_rejects_unknown_commands_and_digests():
    for recovery in [
        {"operation": "SHELL", "command": "rm -rf /"},
        {"operation": "START", "digest": "latest"},
    ]:
        with pytest.raises(ValidationError):
            AnalyzeDeploymentSources.model_validate({"version": 1, "recovery": recovery})


def context(monkeypatch):
    monkeypatch.setenv("MIGRATION_RECOVERY_BUCKET", "test-private-recovery")
    migration = {
        "customer_id": "CUS-test",
        "migration_id": "MIG-test",
        "created_by": "tester",
        "version": 2,
        "source_configuration": {"sourceClusterId": "SRC-test"},
    }
    source = {
        "source_cluster_id": "SRC-test",
        "customer_id": "CUS-test",
        "delivery_method": "AWS_SSM",
        "delivery_configuration": {},
    }
    service = MagicMock()
    service.deployment_context.return_value = (migration, source)
    service.repo.get_source_cluster.return_value = source
    service.repo.get_source_inventory.return_value = {"inventory": {"inventoryDigest": "inventory-one"}}
    report = {
        "workloads": [
            {
                "workload": {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "namespace": "shop",
                    "name": "api",
                },
                "containers": [
                    {
                        "name": "api",
                        "containerType": "APPLICATION",
                        "configuredImage": "example/api:tag",
                        "observedDigests": ["sha256:" + "a" * 64],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(
        "navigan.modules.migration_management.deployment_sources.build_report", lambda *args: report
    )
    return service, source, report


def test_recovery_requires_observed_digest_not_mutable_tag(monkeypatch):
    service, source, report = context(monkeypatch)
    request = {
        "operation": "START",
        "artifactKind": "IMAGE",
        **report["workloads"][0]["workload"],
        "containerName": "api",
        "containerType": "APPLICATION",
        "digest": "sha256:" + "b" * 64,
    }
    with pytest.raises(ApiError) as error:
        recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=MagicMock())
    assert error.value.code == "RECOVERY_DIGEST_REQUIRED"
    service.repo.save_deployment_configuration.assert_not_called()


def test_recovery_is_scoped_and_fails_without_storage(monkeypatch):
    service, _, _ = context(monkeypatch)
    monkeypatch.delenv("MIGRATION_RECOVERY_BUCKET")
    with pytest.raises(ApiError) as error:
        recover(service, "MIG-test", {"version": 2, "recovery": {"operation": "START"}}, factory=MagicMock())
    assert error.value.code == "RECOVERY_STORAGE_REQUIRED"
    service.access.require_customer.assert_called_once_with("CUS-test", "tester")
    with pytest.raises(ApiError):
        storage_key({"customer_id": "../other", "migration_id": "MIG-test"}, "REC-test")


def test_download_cannot_cross_migration_or_inventory(monkeypatch):
    service, source, _ = context(monkeypatch)
    source["delivery_configuration"]["artifactRecovery"] = {"OTHER": [{"jobId": "REC-test"}]}
    body = {"version": 2, "recovery": {"operation": "DOWNLOAD", "jobId": "REC-test"}}
    with pytest.raises(ApiError) as error:
        recover(service, "MIG-test", body, factory=MagicMock())
    assert error.value.code == "RECOVERY_NOT_FOUND"
    source["delivery_configuration"]["artifactRecovery"]["MIG-test"] = [
        {"jobId": "REC-test", "inventoryDigest": "old"}
    ]
    with pytest.raises(ApiError) as error:
        recover(service, "MIG-test", body, factory=MagicMock())
    assert error.value.code == "RECOVERY_EVIDENCE_CHANGED"


def test_public_job_never_exposes_internal_storage_or_ssm_handles():
    assert public_job(
        {
            "jobId": "REC-test",
            "objectKey": "private/key",
            "parameterName": "private/path",
            "commandId": "internal",
            "status": "RECOVERING",
        }
    ) == {"jobId": "REC-test", "status": "RECOVERING"}


def test_helm_release_recovery_is_partial_and_does_not_claim_original_chart(monkeypatch, tmp_path):
    import gzip
    from navigan.modules.migration_management import recovery_worker as worker

    release = {
        "name": "app",
        "namespace": "shop",
        "version": 3,
        "chart": {"metadata": {"name": "app", "version": "1.0"}},
        "config": {"private": "private-test-value"},
        "manifest": "kind: Secret",
    }
    packed = base64.b64encode(base64.b64encode(gzip.compress(json.dumps(release).encode()))).decode()
    secrets = {"items": [{"metadata": {"labels": {"version": "3"}}, "data": {"release": packed}}]}
    monkeypatch.setattr(worker, "run", lambda *args: json.dumps(secrets).encode())
    path, result = worker.recover_helm(
        {"namespace": "shop", "release": "app", "kubeconfigPath": "/test/config"}, tmp_path
    )
    assert result["status"] == "PARTIAL_RECOVERY"
    assert "private-test-value" not in json.dumps(result)
    assert "Secret" not in json.dumps(result)
    assert json.loads(gzip.decompress(path.read_bytes()))["version"] == 3
    with pytest.raises(ValueError, match="RELEASE_IDENTITY_MISMATCH"):
        worker.recover_helm(
            {"namespace": "shop", "release": "different", "kubeconfigPath": "/test/config"}, tmp_path
        )


def test_recovery_start_presigns_only_scoped_object_and_does_not_expose_url(monkeypatch):
    service, source, report = context(monkeypatch)
    ssm = MagicMock()
    ssm.send_command.return_value = {"Command": {"CommandId": "command-test"}}
    s3 = MagicMock()
    s3.generate_presigned_url.return_value = "https://private.example/upload?token=private"
    monkeypatch.setattr(
        "navigan.modules.migration_management.artifact_recovery.ssm_client", lambda *args: ssm
    )
    source["delivery_configuration"].update(
        kubeconfigPath="/test/config", region="test-region", managedInstanceId="i-test"
    )
    request = {
        "operation": "START",
        "artifactKind": "IMAGE",
        **report["workloads"][0]["workload"],
        "containerName": "api",
        "containerType": "APPLICATION",
        "digest": "sha256:" + "a" * 64,
    }
    response = recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda name: s3)
    assert response["job"]["status"] == "RECOVERING"
    assert "token=private" not in json.dumps(response)
    s3.generate_presigned_url.assert_not_called()
    payload = service.repo.save_deployment_configuration.call_args.args[2]
    key = payload["MIG-test"][0]["objectKey"]
    assert key.startswith("customers/CUS-test/migrations/MIG-test/recovery/")
    assert ssm.send_command.call_args.kwargs["InstanceIds"] == ["i-test"]
    assert "private.example" not in str(ssm.send_command.call_args)
    service.repo.save_deployment_configuration.assert_called_once()


def test_poll_rejects_successful_command_without_matching_s3_checksum(monkeypatch):
    service, source, _ = context(monkeypatch)
    job = {
        "jobId": "REC-test",
        "kind": "IMAGE",
        "phase": "UPLOAD",
        "digest": "sha256:" + "c" * 64,
        "inventoryDigest": "inventory-one",
        "status": "RECOVERING",
        "commandId": "command-test",
        "managedInstanceId": "i-test",
        "parameterName": "private-parameter",
        "objectKey": "private-key",
    }
    source["delivery_configuration"]["artifactRecovery"] = {"MIG-test": [job]}
    ssm = MagicMock()
    ssm.get_command_invocation.return_value = {
        "Status": "Success",
        "StandardOutputContent": json.dumps(
            {
                "status": "RECOVERED",
                "format": "OCI_ARCHIVE",
                "digest": "sha256:" + "c" * 64,
                "sha256": "a" * 64,
                "sizeBytes": 10,
            }
        ),
    }
    s3 = MagicMock()
    s3.head_object.return_value = {
        "ChecksumSHA256": "wrong",
        "ContentLength": 10,
        "ServerSideEncryption": "AES256",
    }
    monkeypatch.setattr(
        "navigan.modules.migration_management.artifact_recovery.ssm_client", lambda *args: ssm
    )
    result = recover(
        service,
        "MIG-test",
        {"version": 2, "recovery": {"operation": "POLL", "jobId": "REC-test"}},
        factory=lambda name: s3,
    )
    assert result["job"]["status"] == "CUSTOMER_INPUT_REQUIRED"
    assert "downloadUrl" not in result


def test_expired_recovered_object_does_not_offer_download(monkeypatch):
    service, source, _ = context(monkeypatch)
    job = {
        "jobId": "REC-test",
        "inventoryDigest": "inventory-one",
        "status": "RECOVERED",
        "kind": "IMAGE",
        "objectKey": "private-key",
        "sha256": "a" * 64,
        "sizeBytes": 10,
    }
    source["delivery_configuration"]["artifactRecovery"] = {"MIG-test": [job]}
    client = MagicMock()
    client.head_object.side_effect = RuntimeError("missing")
    with pytest.raises(ApiError) as error:
        recover(
            service,
            "MIG-test",
            {"version": 2, "recovery": {"operation": "DOWNLOAD", "jobId": "REC-test"}},
            factory=lambda name: client,
        )
    assert error.value.code == "RECOVERY_ARTIFACT_UNAVAILABLE"
    client.generate_presigned_url.assert_not_called()


def test_export_upload_and_validation_are_separate_phases(monkeypatch):
    service, source, _ = context(monkeypatch)
    job = {
        "jobId": "REC-test",
        "kind": "IMAGE",
        "phase": "EXPORT",
        "digest": "sha256:" + "c" * 64,
        "inventoryDigest": "inventory-one",
        "status": "RECOVERING",
        "commandId": "command-test",
        "managedInstanceId": "i-test",
        "parameterName": "private-parameter",
        "objectKey": "private-key",
    }
    source["delivery_configuration"]["artifactRecovery"] = {"MIG-test": [job]}
    exported = {
        "status": "EXPORT_READY",
        "artifactStatus": "RECOVERED",
        "format": "OCI_ARCHIVE",
        "digest": job["digest"],
        "sha256": "a" * 64,
        "sizeBytes": 10,
        "message": "Validated export",
    }
    ssm = MagicMock()
    ssm.get_command_invocation.return_value = {
        "Status": "Success",
        "StandardOutputContent": json.dumps(exported),
    }
    s3 = MagicMock()
    s3.generate_presigned_url.return_value = "https://example.test/signed-upload"
    monkeypatch.setattr(
        "navigan.modules.migration_management.artifact_recovery.ssm_client", lambda *args: ssm
    )
    dispatch = MagicMock(return_value=("upload-command", "upload-parameter"))
    monkeypatch.setattr("navigan.modules.migration_management.artifact_recovery.dispatch", dispatch)
    body = {"version": 2, "recovery": {"operation": "POLL", "jobId": "REC-test"}}
    result = recover(service, "MIG-test", body, factory=lambda name: s3)
    assert result["job"]["status"] == "RECOVERING"
    assert result["job"]["phase"] == "UPLOAD"
    assert (
        s3.generate_presigned_url.call_args.kwargs["Params"]["ChecksumSHA256"]
        == base64.b64encode(bytes.fromhex("a" * 64)).decode()
    )
    assert dispatch.call_args.args[2]["sha256"] == "a" * 64
    s3.head_object.assert_not_called()
    completed = {**exported, "status": "RECOVERED"}
    ssm.get_command_invocation.return_value = {
        "Status": "Success",
        "StandardOutputContent": json.dumps(completed),
    }
    s3.head_object.return_value = {
        "ChecksumSHA256": base64.b64encode(bytes.fromhex("a" * 64)).decode(),
        "ContentLength": 10,
        "ServerSideEncryption": "AES256",
        "VersionId": "object-version",
    }
    result = recover(service, "MIG-test", body, factory=lambda name: s3)
    assert result["job"]["status"] == "RECOVERED"
    assert "objectVersion" not in result["job"]
    assert job["objectVersion"] == "object-version"
