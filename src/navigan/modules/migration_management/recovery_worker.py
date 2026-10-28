"""SSM-host recovery worker. Standard library only; never pulls or changes workloads.

Input is a short-lived SecureString, not a user-supplied shell command. Exports
only retained Helm release data or a complete locally cached OCI image.
"""

import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

MAX_ARCHIVE = 2 * 1024**3
DIGEST = re.compile(r"sha256:[a-f0-9]{64}$")


def run(args, limit=8 * 1024**2):
    # Never surface stderr: Helm release content and node credentials are private.
    with tempfile.TemporaryFile() as output:
        subprocess.run(args, stdout=output, stderr=subprocess.DEVNULL, check=True, timeout=480)
        if output.tell() > limit:
            raise ValueError("OUTPUT_LIMIT")
        output.seek(0)
        return output.read()


def validate_oci(path, expected):
    """Verify every reachable descriptor, not merely existence of an image tag."""
    if not DIGEST.fullmatch(expected):
        raise ValueError("DIGEST_REQUIRED")
    if path.stat().st_size > MAX_ARCHIVE:
        raise ValueError("ARCHIVE_LIMIT")
    with tarfile.open(path) as archive:
        members = []
        for member in archive:
            if (
                member.issym()
                or member.islnk()
                or member.name.startswith("/")
                or ".." in Path(member.name).parts
            ):
                raise ValueError("INVALID_ARCHIVE")
            members.append(member)
            if len(members) > 20000:
                raise ValueError("INVALID_ARCHIVE")
        names = [m.name.removeprefix("./") for m in members]
        if len(names) != len(set(names)) or len(names) > 20000:
            raise ValueError("INVALID_ARCHIVE")
        lookup = dict(zip(names, members))

        def read(name, limit):
            member = lookup.get(name)
            if member is None or not member.isfile() or member.size > limit:
                raise ValueError("INCOMPLETE_ARCHIVE")
            return archive.extractfile(member).read(limit + 1)

        index = json.loads(read("index.json", 4 * 1024**2))
        visited = set()

        def verify(descriptor):
            digest = descriptor.get("digest", "")
            if not DIGEST.fullmatch(digest):
                raise ValueError("INVALID_DIGEST")
            if digest in visited:
                return
            visited.add(digest)
            member = lookup.get("blobs/sha256/" + digest[7:])
            if not member or not member.isfile() or member.size != descriptor.get("size"):
                raise ValueError("INCOMPLETE_ARCHIVE")
            handle = archive.extractfile(member)
            sha = hashlib.sha256()
            while data := handle.read(1024**2):
                sha.update(data)
            if sha.hexdigest() != digest[7:]:
                raise ValueError("DIGEST_MISMATCH")
            media = descriptor.get("mediaType", "")
            if "manifest" in media or "index" in media or "manifest.list" in media:
                value = json.loads(read(member.name.removeprefix("./"), 4 * 1024**2))
                for child in (
                    value.get("manifests", [])
                    + value.get("layers", [])
                    + ([value["config"]] if "config" in value else [])
                ):
                    verify(child)

        for item in index.get("manifests", []):
            verify(item)
        if expected not in visited:
            raise ValueError("EXPECTED_IMAGE_NOT_EXPORTED")
    return len(visited)


def recover_image(value, work):
    expected = value["digest"]
    if not DIGEST.fullmatch(expected):
        raise ValueError("DIGEST_REQUIRED")
    # Local containerd only. No registry pull, no privileged Pod, no SSH fan-out.
    lines = run(["ctr", "-n", "k8s.io", "images", "ls"]).decode().splitlines()[1:]
    matches = [line.split()[0] for line in lines if len(line.split()) >= 3 and line.split()[2] == expected]
    if not matches:
        raise ValueError("CACHE_NOT_FOUND_ON_CONFIGURED_HOST")
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if not arch:
        raise ValueError("UNSUPPORTED_PLATFORM")
    import resource

    available = shutil.disk_usage(work).free - 1024**3
    if available <= 0:
        raise ValueError("SOURCE_DISK_SPACE_REQUIRED")
    cap = min(MAX_ARCHIVE, available)
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
    path = work / "image.oci.tar"
    run(
        ["ctr", "-n", "k8s.io", "images", "export", "--platform", "linux/" + arch, str(path), matches[0]],
        limit=65536,
    )
    count = validate_oci(path, expected)
    return path, {
        "status": "RECOVERED",
        "format": "OCI_ARCHIVE",
        "digest": expected,
        "platform": "linux/" + arch,
        "verifiedBlobCount": count,
        "message": "Complete cached image exported and digest-validated on the configured SSM host. Other platforms and nodes were not checked.",
    }


def recover_helm(value, work):
    namespace, release = value["namespace"], value["release"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", release) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,62}", namespace
    ):
        raise ValueError("INVALID_RELEASE")
    raw = run(
        [
            "kubectl",
            "--kubeconfig",
            value["kubeconfigPath"],
            "-n",
            namespace,
            "get",
            "secrets",
            "-l",
            "owner=helm,name=" + release + ",status=deployed",
            "-o",
            "json",
        ]
    )
    secrets = json.loads(raw).get("items", [])
    if not secrets:
        raise ValueError("HELM_RELEASE_NOT_RETAINED")

    def revision(item):
        return int(item.get("metadata", {}).get("labels", {}).get("version", "0"))

    secret = max(secrets, key=revision)
    encoded = base64.b64decode(secret["data"]["release"], validate=True)
    packed = base64.b64decode(encoded, validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as handle:
        decoded = handle.read(16 * 1024**2 + 1)
    if len(decoded) > 16 * 1024**2:
        raise ValueError("RELEASE_LIMIT")
    data = json.loads(decoded)
    if data.get("name") != release or data.get("namespace") != namespace:
        raise ValueError("RELEASE_IDENTITY_MISMATCH")
    # Retain release data privately, never return values or rendered Secrets in API output.
    bundle = {
        k: data[k]
        for k in ("name", "namespace", "version", "chart", "config", "manifest", "hooks")
        if k in data
    }
    bundle["recoveryNotice"] = (
        "Retained Helm release data; not the original signed chart package. Review dependencies, secrets and environment-specific values before use."
    )
    path = work / "helm-release.json.gz"
    with gzip.open(path, "wb") as handle:
        handle.write(json.dumps(bundle).encode())
    return path, {
        "status": "PARTIAL_RECOVERY",
        "format": "HELM_RELEASE_BUNDLE",
        "namespace": namespace,
        "release": release,
        "releaseRevision": data.get("version"),
        "message": "Retained Helm release data recovered. Original chart archive, signatures and dependency completeness are unverified. Contains sensitive configuration; review before use.",
    }


def recover_definition(value, work):
    resource = value["resource"]
    kinds = {"Deployment": "deployments.apps", "StatefulSet": "statefulsets.apps",
             "DaemonSet": "daemonsets.apps", "Job": "jobs.batch", "CronJob": "cronjobs.batch"}
    kind, namespace, name = (resource[k] for k in ("kind", "namespace", "name"))
    if (kind not in kinds or resource.get("apiVersion") != ("batch/v1" if kind in {"Job", "CronJob"} else "apps/v1")
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", namespace)
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", name)):
        raise ValueError("INVALID_RESOURCE")
    data = json.loads(run(["kubectl", "--kubeconfig", value["kubeconfigPath"], "-n", namespace,
                           "get", kinds[kind], name, "-o", "json"]))
    metadata = data.get("metadata", {})
    if (data.get("apiVersion") != resource["apiVersion"] or data.get("kind") != kind
            or metadata.get("namespace") != namespace or metadata.get("name") != name):
        raise ValueError("RESOURCE_IDENTITY_MISMATCH")
    if not isinstance(data.get("spec"), dict) or metadata.get("deletionTimestamp"):
        raise ValueError("RESOURCE_UNAVAILABLE")
    def clean_metadata(meta):
        for key in ("uid", "resourceVersion", "generation", "creationTimestamp", "deletionTimestamp",
                    "deletionGracePeriodSeconds", "managedFields", "ownerReferences", "finalizers", "selfLink"):
            meta.pop(key, None)
        annotations = meta.get("annotations", {})
        annotations.pop("kubectl.kubernetes.io/last-applied-configuration", None)
        if not annotations:
            meta.pop("annotations", None)
    clean_metadata(metadata)
    template = data["spec"].get("jobTemplate", {}) if kind == "CronJob" else data
    clean_metadata(template.get("metadata", {}))
    clean_metadata(template.get("spec", {}).get("template", {}).get("metadata", {}))
    data.pop("status", None)
    path = work / "live-definition.json"
    path.write_text(json.dumps(data, sort_keys=True))
    os.chmod(path, 0o600)
    return path, {"status": "PARTIAL_RECOVERY", "format": "KUBERNETES_JSON", "resource": resource,
                  "message": "Live definition saved. Review configuration, credentials, dependencies and cluster-specific settings before deployment."}


def artifact_filename(kind):
    return {"IMAGE": "image.oci.tar", "HELM_RELEASE": "helm-release.json.gz",
            "LIVE_DEFINITION": "live-definition.json"}[kind]


def execute(value):
    job_id = value["jobId"]
    if not re.fullmatch(r"REC-[a-f0-9]{32}", job_id):
        raise ValueError("INVALID_JOB")
    # Only private, server-created job paths. Never accept an arbitrary host path.
    root = Path("/var/lib/navigan/source-recovery")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    work = root / job_id
    if not work.exists() and sum(1 for child in root.iterdir() if child.is_dir()) >= 2:
        raise ValueError("SOURCE_RECOVERY_WORKSPACE_BUSY")
    work.mkdir(exist_ok=True, mode=0o700)
    os.chmod(work, 0o700)
    record_path = work / "export.json"
    if value.get("phase") == "UPLOAD":
        result = json.loads(record_path.read_text())
        path = work / artifact_filename(value["kind"])
    else:
        path, result = {"IMAGE": recover_image, "HELM_RELEASE": recover_helm,
                        "LIVE_DEFINITION": recover_definition}[value["kind"]](value, work)
    size = path.stat().st_size
    if not 0 < size <= MAX_ARCHIVE:
        raise ValueError("ARCHIVE_LIMIT")
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024**2):
            sha.update(chunk)
    result.update(sha256=sha.hexdigest(), sizeBytes=size)
    if value.get("phase") != "UPLOAD":
        record_path.write_text(json.dumps(result))
        os.chmod(record_path, 0o600)
        return {**result, "artifactStatus": result["status"], "status": "EXPORT_READY"}
    if result["sha256"] != value["sha256"] or size != value["sizeBytes"]:
        raise ValueError("DIGEST_MISMATCH")
    checksum = base64.b64encode(sha.digest()).decode()
    # The checksum is known before this upload URL is signed by the API.
    with path.open("rb") as handle:
        request = urllib.request.Request(
            value["uploadUrl"],
            data=handle,
            method="PUT",
            headers={
                "Content-Length": str(size),
                "x-amz-checksum-sha256": checksum,
                "x-amz-server-side-encryption": "AES256",
                **value.get("storageHeaders", {}),
                "Content-Type": "application/octet-stream",
            },
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            if response.status != 200:
                raise ValueError("UPLOAD_FAILED")
    path.unlink()
    record_path.unlink()
    work.rmdir()
    return result


if __name__ == "__main__":
    import sys

    try:
        with open(sys.argv[1]) as handle:
            value = json.load(handle)
        print(json.dumps(execute(value), separators=(",", ":")))
    except Exception as error:
        if isinstance(locals().get("value"), dict) and re.fullmatch(
            r"REC-[a-f0-9]{32}", value.get("jobId", "")
        ):
            work = Path("/var/lib/navigan/source-recovery") / value["jobId"]
            for name in ("image.oci.tar", "helm-release.json.gz", "live-definition.json", "export.json"):
                try:
                    (work / name).unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                work.rmdir()
            except OSError:
                pass
        known = {
            "SOURCE_RECOVERY_WORKSPACE_BUSY",
            "SOURCE_DISK_SPACE_REQUIRED",
            "DIGEST_REQUIRED",
            "CACHE_NOT_FOUND_ON_CONFIGURED_HOST",
            "UNSUPPORTED_PLATFORM",
            "INCOMPLETE_ARCHIVE",
            "EXPECTED_IMAGE_NOT_EXPORTED",
            "DIGEST_MISMATCH",
            "HELM_RELEASE_NOT_RETAINED",
            "RELEASE_LIMIT",
            "RESOURCE_IDENTITY_MISMATCH",
            "RESOURCE_UNAVAILABLE",
            "ARCHIVE_LIMIT",
        }
        reason = str(error) if str(error) in known else "RECOVERY_FAILED_CHECK_HOST_ACCESS_AND_RUNTIME"
        print(json.dumps({"status": "CUSTOMER_INPUT_REQUIRED", "message": reason}))
