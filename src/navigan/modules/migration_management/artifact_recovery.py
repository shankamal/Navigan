"""Authorized, asynchronous source artifact recovery through an existing SSM host.

No node privileges are added to the connector and no image is pulled or promoted.
Recovery records remain scoped to customer, migration and inventory digest.
"""

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import uuid

from navigan.shared.errors import ApiError


def public_job(job):
    return {
        k: v for k, v in job.items() if k not in {"objectKey", "objectVersion", "commandId", "parameterName", "expectedSha256", "expectedSizeBytes"}
    }


def storage_key(migration, job_id):
    values = [migration["customer_id"], migration["migration_id"], job_id]
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v) for v in values):
        raise ApiError(400, "INVALID_RECOVERY_IDENTITY", "Invalid recovery identity.")
    return f"customers/{values[0]}/migrations/{values[1]}/recovery/{job_id}/artifact"


def ssm_client(source, factory):
    delivery = source.get("delivery_configuration") or {}
    role = (
        delivery.get("roleArn")
        or f"arn:aws:iam::{delivery.get('accountId')}:role/NaviganSourceConnectorDeliveryRole"
    )
    if source.get("delivery_method") != "AWS_SSM" or role != os.environ.get(
        "SOURCE_CONNECTOR_DELIVERY_ROLE_ARN"
    ):
        raise ApiError(
            409,
            "RECOVERY_ACCESS_REQUIRED",
            "Recovery requires an approved source SSM host. The read-only connector cannot inspect node caches.",
        )
    assumed = factory("sts").assume_role(
        RoleArn=role,
        RoleSessionName="NaviganRecovery",
        ExternalId=source["source_cluster_id"],
        DurationSeconds=900,
    )["Credentials"]
    return factory(
        "ssm",
        region_name=delivery["region"],
        aws_access_key_id=assumed["AccessKeyId"],
        aws_secret_access_key=assumed["SecretAccessKey"],
        aws_session_token=assumed["SessionToken"],
    )


def dispatch(ssm, source, payload):
    delivery = source["delivery_configuration"]
    parameter = "/navigan/migration/source-connectors/" + source["source_cluster_id"] + "/" + uuid.uuid4().hex
    encoded = json.dumps(payload)
    ssm.put_parameter(
        Name=parameter,
        Type="SecureString",
        Value=encoded,
        Overwrite=False,
        Tier="Advanced" if len(encoded) > 4096 else "Standard",
    )
    script = base64.b64encode(Path(__file__).with_name("recovery_worker.py").read_bytes()).decode()
    commands = [
        "set -eu",
        "umask 077",
        "work=$(mktemp -d /tmp/navigan-recovery.XXXXXX)",
        "trap 'rm -rf \"$work\"' EXIT",
        "aws ssm get-parameter --region "
        + shlex.quote(delivery["region"])
        + " --with-decryption --name "
        + shlex.quote(parameter)
        + ' --query Parameter.Value --output text > "$work/request.json"',
        "aws ssm delete-parameter --region "
        + shlex.quote(delivery["region"])
        + " --name "
        + shlex.quote(parameter),
        "printf '%s' '" + script + '\' | base64 -d > "$work/recover.py"',
        'python3 "$work/recover.py" "$work/request.json"',
    ]
    try:
        command = ssm.send_command(
            InstanceIds=[delivery["managedInstanceId"]],
            DocumentName="AWS-RunShellScript",
            Comment="Recover source artifact without changing workloads",
            TimeoutSeconds=900,
            Parameters={"commands": commands, "executionTimeout": ["1200"]},
        )
    except Exception:
        ssm.delete_parameter(Name=parameter)
        raise ApiError(
            503, "RECOVERY_START_FAILED", "Unable to start recovery through the configured SSM host."
        ) from None
    return command["Command"]["CommandId"], parameter


def validate_result(job, result):
    if job["kind"] == "IMAGE" and (
        result.get("digest") != job.get("digest")
        or result.get("format") != "OCI_ARCHIVE"
        or result.get("status") != "RECOVERED"
    ):
        raise ValueError()
    if job["kind"] == "HELM_RELEASE" and (
        result.get("format") != "HELM_RELEASE_BUNDLE" or result.get("status") != "PARTIAL_RECOVERY"
    ):
        raise ValueError()
    if job["kind"] == "HELM_RELEASE" and job.get("workspaceId") and (
        result.get("namespace") != job["workload"]["namespace"] or result.get("release") != job.get("release")
    ):
        raise ValueError()
    if job["kind"] == "LIVE_DEFINITION" and (
        result.get("format") != "KUBERNETES_JSON" or result.get("status") != "PARTIAL_RECOVERY"
        or result.get("resource") != job["workload"]
    ):
        raise ValueError()
    sha = result["sha256"]
    if (
        not re.fullmatch(r"[a-f0-9]{64}", sha)
        or type(result["sizeBytes"]) is not int
        or not 0 < result["sizeBytes"] <= 2 * 1024**3
    ):
        raise ValueError()
    return sha


def workspace_context(service, identifier, request):
    """Resolve identities from the authorized snapshot, never client workload fields."""
    from .artifact_workspace import read, storage_configuration
    workspace_id, artifact_id = request.get("workspaceId"), request.get("artifactId")
    if not workspace_id and not artifact_id:
        if request.get("artifactKind") == "LIVE_DEFINITION":
            raise ApiError(400, "WORKSPACE_REQUIRED", "Choose a live definition in a workspace.")
        return None
    if not workspace_id or not artifact_id:
        raise ApiError(400, "WORKSPACE_ARTIFACT_REQUIRED", "Choose a workspace and its artifact.")
    workspace = read(service, identifier, workspace_id)
    if workspace["stale"]:
        raise ApiError(409, "STALE_WORKSPACE", "Inventory changed. Create a workspace from current discovery.")
    artifact = next((a for a in workspace["artifacts"] if a["artifactId"] == artifact_id), None)
    if not artifact or artifact["kind"] not in {"LIVE_DEFINITION", "HELM_RELEASE"}:
        raise ApiError(400, "RECOVERY_ARTIFACT_REQUIRED", "Choose a cluster definition or Helm release in this workspace.")
    if artifact["status"] == "EXCLUDED_FROM_REPLAY":
        raise ApiError(409, "HISTORICAL_REVIEW_EXISTS", "This Job run is excluded from replay by a recorded review.")
    if request["operation"] == "START" and artifact["status"] == "COLLECTED":
        raise ApiError(409, "ARTIFACT_ALREADY_COLLECTED", "This artifact is already saved to S3.")
    bucket, key, owner = storage_configuration()
    rows = service.repo.list_artifact_workspaces(identifier, workspace["customerId"], workspace_id)
    if not rows or rows[0]["bucket_name"] != bucket:
        raise ApiError(409, "WORKSPACE_STORAGE_CHANGED", "Workspace storage configuration changed.")
    return workspace, artifact, bucket, key, owner


def record_workspace_recovery(service, job):
    if not job.get("workspaceId"):
        return
    from .artifact_workspace import canonical
    recovered = job["status"] in {"RECOVERED", "PARTIAL_RECOVERY"}
    validation = {"recovery": public_job(job), "targetReady": False, "reviewRequired": True,
                  "originalSourceVerified": False}
    service.repo.db.execute(
        "UPDATE migration_management.workspace_artifacts SET status=%s,validation=%s::jsonb,"
        "object_key=%s,object_version=%s,sha256=%s,size_bytes=%s,updated_at=now() "
        "WHERE workspace_id=%s AND artifact_id=%s",
        ["COLLECTED" if recovered else ("RECOVERING" if job["status"] == "RECOVERING" else "RECOVERY_REQUIRED"),
         canonical(validation).decode(), job["objectKey"] if recovered else None,
         job.get("objectVersion") if recovered else None, job.get("sha256") if recovered else None,
         job.get("sizeBytes") if recovered else None, job["workspaceId"], job["artifactId"]])


def recover(service, identifier, body, factory=None):
    if body.get("recovery", {}).get("operation") == "EXCLUDE_HISTORICAL_JOB":
        from .artifact_workspace import exclude_historical_job
        return {"workspace": exclude_historical_job(service, identifier, body, client=factory("s3") if factory else None)}
    service.access.require("migration.edit")
    migration, source = service.deployment_context(identifier)
    service.access.require_customer(migration["customer_id"], migration["created_by"])
    if migration["version"] != body["version"]:
        raise ApiError(409, "CONCURRENT_UPDATE", "Reload this assessment before resolving artifacts.")
    from .deployment_sources import build_report

    inventory = service.repo.get_source_inventory(identifier).get("inventory")
    if not inventory:
        raise ApiError(409, "SOURCE_INVENTORY_REQUIRED", "Complete source discovery first.")
    report = build_report(migration, inventory, source)
    request = body["recovery"]
    binding = workspace_context(service, identifier, request)
    if binding:
        workspace, artifact, bucket, key_id, owner = binding
        storage_options = {"ExpectedBucketOwner": owner}
        encryption = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": key_id}
        storage_headers = {"x-amz-server-side-encryption": "aws:kms",
                           "x-amz-server-side-encryption-aws-kms-key-id": key_id,
                           "x-amz-expected-bucket-owner": owner}
    else:
        bucket = os.environ.get("MIGRATION_RECOVERY_BUCKET", "")
        storage_options, storage_headers = {}, {}
        encryption = {"ServerSideEncryption": "AES256"}
    if not bucket:
        raise ApiError(
            503,
            "RECOVERY_STORAGE_REQUIRED",
            "Private recovery artifact storage must be configured before recovering artifacts.",
        )
    if factory is None:
        import boto3
        from botocore.config import Config

        def factory(name, **options):
            if name == "s3":
                options["config"] = Config(signature_version="s3v4")
            return boto3.client(name, **options)

    # Lock the source before changing the shared, migration-keyed job list.
    source = service.repo.get_source_cluster(source["source_cluster_id"], lock=True)
    jobs = dict((source.get("delivery_configuration") or {}).get("artifactRecovery", {}))
    current = list(jobs.get(identifier, []))
    operation = request["operation"]
    if operation in {"POLL", "DOWNLOAD"}:
        job = next((j for j in current if j["jobId"] == request.get("jobId")), None)
        if not job:
            raise ApiError(404, "RECOVERY_NOT_FOUND", "Recovery was not found for this assessment.")
        if (job.get("workspaceId") != request.get("workspaceId")
                or job.get("artifactId") != request.get("artifactId")):
            raise ApiError(404, "RECOVERY_NOT_FOUND", "Recovery was not found for this workspace artifact.")
        if job["inventoryDigest"] != inventory.get("inventoryDigest"):
            raise ApiError(
                409,
                "RECOVERY_EVIDENCE_CHANGED",
                "Inventory changed. Start a new recovery from current evidence.",
            )
        if operation == "DOWNLOAD":
            if job["status"] not in {"RECOVERED", "PARTIAL_RECOVERY"}:
                raise ApiError(409, "RECOVERY_NOT_READY", "No validated recovery artifact is available.")
            s3 = factory("s3")
            version = {"VersionId": job["objectVersion"]} if job.get("objectVersion") else {}
            try:
                head = s3.head_object(Bucket=bucket, Key=job["objectKey"], ChecksumMode="ENABLED", **storage_options, **version)
                if (
                    head.get("ChecksumSHA256") != base64.b64encode(bytes.fromhex(job["sha256"])).decode()
                    or head["ContentLength"] != job["sizeBytes"]
                    or head.get("ServerSideEncryption") != encryption["ServerSideEncryption"]
                    or (binding and (not job.get("objectVersion") or head.get("SSEKMSKeyId") != key_id))
                ):
                    raise ValueError()
            except Exception:
                raise ApiError(
                    410,
                    "RECOVERY_ARTIFACT_UNAVAILABLE",
                    "The stored recovery artifact expired, is missing or failed integrity checks. Recover again or supply the original artifact.",
                ) from None
            url = s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket,
                    "Key": job["objectKey"],
                    **version,
                    "ResponseContentDisposition": 'attachment; filename="'
                    + ({"IMAGE": "image.oci.tar", "HELM_RELEASE": "helm-release.json.gz", "LIVE_DEFINITION": "live-definition.json"}[job["kind"]])
                    + '"',
                },
                ExpiresIn=300,
            )
            return {"job": public_job(job), "downloadUrl": url}
        if job["status"] == "RECOVERING":
            ssm = ssm_client(source, factory)
            try:
                invocation = ssm.get_command_invocation(
                    CommandId=job["commandId"], InstanceId=job["managedInstanceId"]
                )
            except Exception as error:
                if getattr(error, "response", {}).get("Error", {}).get("Code") == "InvocationDoesNotExist":
                    return {"job": public_job(job)}
                raise ApiError(
                    503, "RECOVERY_STATUS_UNAVAILABLE", "Unable to check source recovery status."
                ) from None
            if invocation["Status"] == "Success":
                try:
                    result = json.loads(invocation.get("StandardOutputContent", ""))
                    if result.get("status") == "EXPORT_READY" and job.get("phase") == "EXPORT":
                        exported = {**result, "status": result.get("artifactStatus")}
                        sha = validate_result(job, exported)
                        checksum = base64.b64encode(bytes.fromhex(sha)).decode()
                        url = factory("s3").generate_presigned_url(
                            "put_object",
                            Params={
                                "Bucket": bucket,
                                "Key": job["objectKey"],
                                "ContentType": "application/octet-stream",
                                **encryption,
                                **storage_options,
                                "ChecksumSHA256": checksum,
                            },
                            ExpiresIn=1800,
                        )
                        command_id, parameter = dispatch(
                            ssm,
                            source,
                            {
                                "phase": "UPLOAD",
                                "jobId": job["jobId"],
                                "kind": job["kind"],
                                "sha256": sha,
                                "sizeBytes": exported["sizeBytes"],
                                "uploadUrl": url,
                                "storageHeaders": storage_headers,
                            },
                        )
                        job.update(
                            expectedSha256=sha,
                            expectedSizeBytes=exported["sizeBytes"],
                            phase="UPLOAD",
                            commandId=command_id,
                            parameterName=parameter,
                            message="Local export validated. Uploading to the private workspace with a signed SHA-256 checksum.",
                        )
                    elif (
                        result.get("status") in {"RECOVERED", "PARTIAL_RECOVERY"}
                        and job.get("phase") == "UPLOAD"
                    ):
                        sha = validate_result(job, result)
                        if (job.get("expectedSha256") and (sha != job["expectedSha256"]
                                or result["sizeBytes"] != job["expectedSizeBytes"])):
                            raise ValueError()
                        head = factory("s3").head_object(
                            Bucket=bucket, Key=job["objectKey"], ChecksumMode="ENABLED", **storage_options
                        )
                        if (
                            head.get("ChecksumSHA256") != base64.b64encode(bytes.fromhex(sha)).decode()
                            or head["ContentLength"] != result["sizeBytes"]
                            or head.get("ServerSideEncryption") != encryption["ServerSideEncryption"]
                            or (binding and (not head.get("VersionId") or head.get("VersionId") == "null" or head.get("SSEKMSKeyId") != key_id))
                        ):
                            raise ValueError()
                        job.update(
                            {
                                key: result[key]
                                for key in (
                                    "status",
                                    "format",
                                    "sha256",
                                    "sizeBytes",
                                    "message",
                                    "platform",
                                    "releaseRevision",
                                    "verifiedBlobCount",
                                )
                                if key in result
                            }
                        )
                        if binding:
                            job["message"] = "Recovered copy saved to the encrypted workspace. Review sensitive configuration, dependencies and target settings before deployment."
                        if head.get("VersionId"):
                            job["objectVersion"] = head["VersionId"]
                        job["completedAt"] = datetime.now(timezone.utc).isoformat()
                    else:
                        job.update(
                            status="CUSTOMER_INPUT_REQUIRED",
                            message="Source export unavailable. Check host access and retained resource data." if binding else result.get("message", "Recovery source unavailable."),
                        )
                except Exception:
                    job.update(
                        status="CUSTOMER_INPUT_REQUIRED",
                        message="Recovery output or stored artifact validation failed. No artifact is marked recovered.",
                    )
            elif invocation["Status"] not in {"Pending", "InProgress", "Delayed"}:
                job.update(
                    status="CUSTOMER_INPUT_REQUIRED",
                    message="Source recovery did not complete. Check SSM access, container runtime and retained release data.",
                )
            if job["status"] != "RECOVERING":
                try:
                    ssm.delete_parameter(Name=job["parameterName"])
                except Exception:
                    pass
    else:
        if binding:
            identity = artifact["source"].get("resource") or artifact["workloads"][0]
            request = {**request, **identity, "artifactKind": artifact["kind"]}
        workload = next(
            (
                w
                for w in report["workloads"]
                if all(
                    w["workload"].get(k) == request.get(k)
                    for k in ("apiVersion", "kind", "namespace", "name")
                )
            ),
            None,
        )
        if not workload:
            raise ApiError(
                400, "RECOVERY_WORKLOAD_NOT_FOUND", "Choose a workload from the current inventory."
            )
        kind = request["artifactKind"]
        payload = {"kind": kind, "namespace": workload["workload"]["namespace"]}
        if kind == "IMAGE":
            container = next(
                (
                    c
                    for c in workload["containers"]
                    if c["name"] == request.get("containerName")
                    and c["containerType"] == request.get("containerType")
                ),
                None,
            )
            if not container:
                raise ApiError(400, "RECOVERY_CONTAINER_NOT_FOUND", "Choose a discovered container.")
            # A current tag is not deployed identity; do not silently recover a newer tag.
            observed = set(container.get("observedDigests", []))
            declared = container["configuredImage"].partition("@")[2]
            digest = request.get("digest")
            if not digest or digest not in observed | ({declared} if declared else set()):
                raise ApiError(
                    409,
                    "RECOVERY_DIGEST_REQUIRED",
                    "Select a declared or observed SHA-256 digest. Refresh runtime evidence when only an image tag is known.",
                )
            payload["digest"] = digest
        elif kind == "LIVE_DEFINITION":
            payload["resource"] = workload["workload"]
        else:
            if not workload.get("helmRelease"):
                raise ApiError(
                    409,
                    "HELM_RELEASE_REQUIRED",
                    "No Helm release identity was detected. Supply the original chart or connect its repository.",
                )
            payload["release"] = workload["helmRelease"]
            if binding and payload["release"] != artifact["source"]["release"]:
                raise ApiError(409, "RECOVERY_EVIDENCE_CHANGED", "The Helm release identity changed.")
        active = next((j for j in current if j["status"] == "RECOVERING"), None)
        if active:
            raise ApiError(
                409,
                "RECOVERY_IN_PROGRESS",
                "Another recovery is running for this assessment. Use Check recovery progress in Migration files & images, or check its workload’s Resolve panel.",
            )
        if len(current) >= 20:
            raise ApiError(
                409,
                "RECOVERY_LIMIT",
                "This assessment has reached its 20 recovery attempts. Review existing artifacts.",
            )
        ssm = ssm_client(source, factory)
        delivery = source["delivery_configuration"]
        job_id = "REC-" + uuid.uuid4().hex
        key = storage_key(migration, job_id)
        if binding:
            from .artifact_workspace import workspace_prefix
            key = workspace_prefix(migration["customer_id"], identifier, workspace["workspaceId"]) + "definitions/recovered/" + job_id + "/artifact"
        payload.update(kubeconfigPath=delivery["kubeconfigPath"], jobId=job_id, phase="EXPORT")
        command_id, parameter = dispatch(ssm, source, payload)
        job = {
            "jobId": job_id,
            "kind": kind,
            "workload": workload["workload"],
            "containerName": request.get("containerName"),
            "digest": payload.get("digest"),
            "inventoryDigest": inventory["inventoryDigest"],
            "status": "RECOVERING",
            "message": "Reading the selected resource from the source cluster through the approved SSM host." if binding else "Checking retained content on the configured SSM host only. Other nodes are not checked. Original source availability remains unchanged.",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "objectKey": key,
            "commandId": command_id,
            "phase": "EXPORT",
            "parameterName": parameter,
            "managedInstanceId": delivery["managedInstanceId"],
        }
        if binding:
            job.update(workspaceId=workspace["workspaceId"], artifactId=artifact["artifactId"], release=payload.get("release"))
        current.append(job)
    record_workspace_recovery(service, job)
    jobs[identifier] = current
    service.repo.save_deployment_configuration(source, "artifactRecovery", jobs, service.correlation)
    return {"job": public_job(job)}
