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


def workspace_setup(monkeypatch, kind="LIVE_DEFINITION"):
    from navigan.modules.migration_management import artifact_workspace
    service, source, report = context(monkeypatch)
    monkeypatch.delenv("MIGRATION_RECOVERY_BUCKET")
    for key, value in {"BUCKET": "workspace-bucket", "KMS_KEY": "arn:aws:kms:test:key/one",
                       "BUCKET_OWNER": "123456789012"}.items():
        monkeypatch.setenv("MIGRATION_WORKSPACE_" + key, value)
    report["workloads"][0]["helmRelease"] = "app"
    artifact = next(a for a in artifact_workspace.plan_artifacts(report, ["shop"]) if a["kind"] == kind)
    workspace_id = "AWS-" + "b" * 32
    service.repo.list_artifact_workspaces.return_value = [
        dict(workspace_id=workspace_id, customer_id="CUS-test", bucket_name="workspace-bucket",
             inventory_digest="inventory-one", source_cluster_id="SRC-test", status="PARTIAL",
             manifest={"workspaceId": workspace_id, "customerId": "CUS-test", "artifacts": [artifact]})]
    service.repo.workspace_collection_state.return_value = ([], [])
    source["delivery_configuration"].update(kubeconfigPath="/test/config", managedInstanceId="i-test", region="test")
    service.repo.save_deployment_configuration.side_effect = lambda _, key, jobs, *args: source["delivery_configuration"].update({key: jobs})
    request = dict(operation="START", workspaceId=workspace_id, artifactId=artifact["artifactId"])
    dispatch = MagicMock(return_value=("command-one", "parameter-one"))
    ssm, s3 = MagicMock(), MagicMock()
    monkeypatch.setattr("navigan.modules.migration_management.artifact_recovery.dispatch", dispatch)
    monkeypatch.setattr("navigan.modules.migration_management.artifact_recovery.ssm_client", lambda *args: ssm)
    return service, source, request, dispatch, ssm, s3, report


@pytest.mark.parametrize("kind", ["LIVE_DEFINITION", "HELM_RELEASE"])
def test_workspace_recovery_binds_identity_and_verifies_versioned_kms_upload(monkeypatch, kind):
    service, source, request, dispatch, ssm, s3, report = workspace_setup(monkeypatch, kind)
    request.update(namespace="other", name="other", artifactKind="IMAGE")
    result = recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda _: s3)
    payload = dispatch.call_args.args[2]
    assert payload["namespace"] == "shop" and payload["kind"] == kind
    assert payload.get("resource", report["workloads"][0]["workload"]) == report["workloads"][0]["workload"]
    job = source["delivery_configuration"]["artifactRecovery"]["MIG-test"][0]
    assert "/workspaces/" + request["workspaceId"] + "/definitions/recovered/" in job["objectKey"]
    assert service.repo.db.execute.call_args.args[1][0] == "RECOVERING"
    exported = dict(status="EXPORT_READY", artifactStatus="PARTIAL_RECOVERY", sha256="a" * 64, sizeBytes=10,
                    resource=report["workloads"][0]["workload"], namespace="shop", release="app",
                    format="KUBERNETES_JSON" if kind == "LIVE_DEFINITION" else "HELM_RELEASE_BUNDLE")
    ssm.get_command_invocation.return_value = {"Status": "Success", "StandardOutputContent": json.dumps(exported)}
    request.update(operation="POLL", jobId=result["job"]["jobId"])
    recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda _: s3)
    signed = s3.generate_presigned_url.call_args.kwargs["Params"]
    assert signed["Bucket"] == "workspace-bucket" and signed["ServerSideEncryption"] == "aws:kms"
    assert signed["ExpectedBucketOwner"] == "123456789012"
    assert dispatch.call_args.args[2]["storageHeaders"]["x-amz-server-side-encryption-aws-kms-key-id"] == signed["SSEKMSKeyId"]
    assert service.repo.db.execute.call_args.args[1][0] == "RECOVERING"
    ssm.get_command_invocation.return_value = {"Status": "Success", "StandardOutputContent": json.dumps({**exported, "status": "PARTIAL_RECOVERY"})}
    s3.head_object.return_value = dict(ChecksumSHA256=base64.b64encode(bytes.fromhex("a" * 64)).decode(),
                                     ContentLength=10, ServerSideEncryption="aws:kms", SSEKMSKeyId=signed["SSEKMSKeyId"], VersionId="pinned-version")
    response = recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda _: s3)
    assert response["job"]["status"] == "PARTIAL_RECOVERY"
    params = service.repo.db.execute.call_args.args[1]
    assert params[0] == "COLLECTED" and params[3] == "pinned-version"
    validation = json.loads(params[1])
    assert validation["targetReady"] is False and validation["reviewRequired"] is True
    assert "objectKey" not in validation["recovery"] and "commandId" not in validation["recovery"]


@pytest.mark.parametrize("change,code", [("stale", "STALE_WORKSPACE"), ("artifact", "RECOVERY_ARTIFACT_REQUIRED"),
                                         ("bucket", "WORKSPACE_STORAGE_CHANGED"), ("collected", "ARTIFACT_ALREADY_COLLECTED")])
def test_workspace_recovery_rejects_invalid_binding_before_ssm(monkeypatch, change, code):
    service, _, request, dispatch, _, s3, _ = workspace_setup(monkeypatch)
    row = service.repo.list_artifact_workspaces.return_value[0]
    if change == "stale": row["inventory_digest"] = "old"
    if change == "bucket": row["bucket_name"] = "different"
    if change == "artifact": request["artifactId"] = "ART-" + "c" * 64
    if change == "collected": row["manifest"]["artifacts"][0]["status"] = "COLLECTED"
    with pytest.raises(ApiError) as error:
        recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda _: s3)
    assert error.value.code == code
    dispatch.assert_not_called()


def test_workspace_recovery_cannot_poll_another_artifact_job(monkeypatch):
    service, source, request, dispatch, _, s3, _ = workspace_setup(monkeypatch)
    response = recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda _: s3)
    job = source["delivery_configuration"]["artifactRecovery"]["MIG-test"][0]
    job["artifactId"] = "ART-" + "c" * 64
    request.update(operation="POLL", jobId=response["job"]["jobId"])
    with pytest.raises(ApiError) as error:
        recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda _: s3)
    assert error.value.code == "RECOVERY_NOT_FOUND"
    assert dispatch.call_count == 1


@pytest.mark.parametrize("bad", [{"VersionId": "null"}, {"SSEKMSKeyId": "wrong"}, {"ChecksumSHA256": "wrong"}, {"ContentLength": 11}])
def test_workspace_upload_integrity_failure_never_marks_collected(monkeypatch, bad):
    service, source, request, _, ssm, s3, report = workspace_setup(monkeypatch)
    result = recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda _: s3)
    job = source["delivery_configuration"]["artifactRecovery"]["MIG-test"][0]
    job.update(phase="UPLOAD", expectedSha256="a" * 64, expectedSizeBytes=10)
    output = dict(status="PARTIAL_RECOVERY", format="KUBERNETES_JSON", resource=report["workloads"][0]["workload"], sha256="a" * 64, sizeBytes=10)
    ssm.get_command_invocation.return_value = {"Status": "Success", "StandardOutputContent": json.dumps(output)}
    s3.head_object.return_value = {**dict(VersionId="one", ServerSideEncryption="aws:kms", SSEKMSKeyId="arn:aws:kms:test:key/one",
        ChecksumSHA256=base64.b64encode(bytes.fromhex("a" * 64)).decode(), ContentLength=10), **bad}
    request.update(operation="POLL", jobId=result["job"]["jobId"])
    response = recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda _: s3)
    assert response["job"]["status"] == "CUSTOMER_INPUT_REQUIRED"
    assert service.repo.db.execute.call_args.args[1][0] == "RECOVERY_REQUIRED"


def test_live_definition_export_removes_runtime_metadata_without_logging_configuration(monkeypatch, tmp_path):
    from navigan.modules.migration_management import recovery_worker as worker
    identity = dict(apiVersion="apps/v1", kind="Deployment", namespace="shop", name="api")
    data = dict(apiVersion="apps/v1", kind="Deployment", metadata=dict(namespace="shop", name="api", uid="old-uid",
        resourceVersion="8", managedFields=[{}], ownerReferences=[{}], finalizers=["cluster"], annotations={"kubectl.kubernetes.io/last-applied-configuration": "private"}),
        status={"replicas": 1}, spec={"template": {"metadata": {"creationTimestamp": None}, "spec": {"containers": [{"name": "api", "env": [{"name": "TOKEN", "value": "private-value"}]}]}}})
    run = MagicMock(return_value=json.dumps(data).encode())
    monkeypatch.setattr(worker, "run", run)
    path, result = worker.recover_definition(dict(resource=identity, kubeconfigPath="/test/config"), tmp_path)
    saved = json.loads(path.read_text())
    assert "status" not in saved and "uid" not in saved["metadata"] and "annotations" not in saved["metadata"]
    assert "creationTimestamp" not in saved["spec"]["template"]["metadata"]
    assert "private-value" in path.read_text() and "private" not in json.dumps(result)
    assert result["resource"] == identity and result["status"] == "PARTIAL_RECOVERY"
    assert run.call_args.args[0][5:8] == ["get", "deployments.apps", "api"]
    data["metadata"]["name"] = "another"
    run.return_value = json.dumps(data).encode()
    with pytest.raises(ValueError, match="RESOURCE_IDENTITY_MISMATCH"):
        worker.recover_definition(dict(resource=identity, kubeconfigPath="/test/config"), tmp_path)


def test_workspace_recovery_denies_customer_access_before_dispatch(monkeypatch):
    service, _, request, dispatch, _, s3, _ = workspace_setup(monkeypatch)
    service.access.require_customer.side_effect = ApiError(403, "FORBIDDEN", "Forbidden")
    with pytest.raises(ApiError):
        recover(service, "MIG-test", {"version": 2, "recovery": request}, factory=lambda _: s3)
    dispatch.assert_not_called()
    service.repo.db.execute.assert_not_called()


def test_workspace_jobs_do_not_appear_in_unbound_legacy_controls(monkeypatch):
    from navigan.modules.migration_management.service import Service
    service, source, _ = context(monkeypatch)
    source["delivery_configuration"]["artifactRecovery"] = {"MIG-test": [
        {"jobId": "REC-legacy", "status": "RECOVERED"},
        {"jobId": "REC-workspace", "workspaceId": "AWS-one", "status": "RECOVERING"}]}
    report = Service.deployment_evidence(service, "MIG-test")
    assert [j["jobId"] for j in report["recoveries"]] == ["REC-legacy"]


def test_workspace_worker_upload_sends_signed_kms_headers_and_removes_local_export(monkeypatch, tmp_path):
    from navigan.modules.migration_management import recovery_worker as worker
    monkeypatch.setattr(worker, "Path", lambda _: tmp_path / "recovery")
    def export(value, work):
        path = work / "live-definition.json"
        path.write_bytes(b'{"kind":"Deployment"}')
        return path, {"status": "PARTIAL_RECOVERY", "format": "KUBERNETES_JSON"}
    monkeypatch.setattr(worker, "recover_definition", export)
    value = dict(jobId="REC-" + "a" * 32, kind="LIVE_DEFINITION", phase="EXPORT")
    result = worker.execute(value)
    assert result["status"] == "EXPORT_READY"
    response = MagicMock()
    response.__enter__.return_value.status = 200
    upload = MagicMock(return_value=response)
    monkeypatch.setattr(worker.urllib.request, "urlopen", upload)
    done = worker.execute({**value, "phase": "UPLOAD", "sha256": result["sha256"],
        "sizeBytes": result["sizeBytes"], "uploadUrl": "https://s3.example/signed",
        "storageHeaders": {"x-amz-server-side-encryption": "aws:kms",
            "x-amz-server-side-encryption-aws-kms-key-id": "key-one", "x-amz-expected-bucket-owner": "123456789012"}})
    request = upload.call_args.args[0]
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["x-amz-server-side-encryption"] == "aws:kms"
    assert headers["x-amz-server-side-encryption-aws-kms-key-id"] == "key-one"
    assert headers["x-amz-expected-bucket-owner"] == "123456789012"
    assert headers["x-amz-checksum-sha256"] == base64.b64encode(bytes.fromhex(result["sha256"])).decode()
    assert done["status"] == "PARTIAL_RECOVERY"
    assert not (tmp_path / "recovery" / value["jobId"]).exists()
