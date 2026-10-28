"""Private, immutable release records shared by the build and DEV executor."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import urllib.parse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "navigan-build-once-v1"
DEV_STACK = "navigan-ashok-dev"
DEV_DATABASE = "navigan_dev"
DEV_API = "https://api-dev.navigan.click"
REGISTRY_PREFIX = "navigan/dev-release"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, Path(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


planner = load("release_impact", ROOT / "scripts/plan-release.py")


class ReleaseError(ValueError):
    """A deliberately sanitized operational message, never an SDK/SQL exception."""


def require(value, message):
    if not value:
        raise ReleaseError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def native_form(value):
    """Normalize the two equivalent Fn::GetAtt JSON spellings for identity checks."""
    if isinstance(value, list):
        return [native_form(item) for item in value]
    if isinstance(value, dict):
        return {key: child.split(".", 1) if key == "Fn::GetAtt" and isinstance(child, str)
                else native_form(child) for key, child in value.items()}
    return value


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never create a briefly world-readable private file.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, default=str)
        stream.write("\n")


def workspace(prefix):
    path = Path(tempfile.mkdtemp(prefix=prefix))
    path.chmod(0o700)
    return path


def run(command, directory, log, *, env=None, data=None):
    with Path(log).open("ab") as output:
        result = subprocess.run(command, cwd=directory, env=env, input=data,
                                stdout=output, stderr=subprocess.STDOUT)
    require(result.returncode == 0, "Command failed; inspect the private stage log.")


def yaml_document(content):
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def intrinsic(loader, tag, node):
        allowed = {"Ref", "Condition", "And", "Base64", "Cidr", "Equals", "FindInMap", "GetAtt",
                   "GetAZs", "If", "ImportValue", "Join", "Length", "Not", "Or", "Select", "Split", "Sub", "ToJsonString"}
        require(tag in allowed, "Unsupported CloudFormation intrinsic.")
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node, deep=True)
        else:
            value = loader.construct_mapping(node, deep=True)
        if tag == "GetAtt" and isinstance(value, str):
            value = value.split(".", 1)
        return {tag if tag in {"Ref", "Condition"} else "Fn::" + tag: value}

    Loader.add_multi_constructor("!", intrinsic)
    value = yaml.load(content, Loader=Loader)
    require(isinstance(value, dict), "Expected a template object.")
    return value


def deterministic_zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            require(not name.startswith("/") and ".." not in PurePosixPath(name).parts and "\\" not in name,
                    "Unsafe package member.")
            item = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, data)
    return output.getvalue()


def unzip(content, maximum=300 * 1024 * 1024):
    result = {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        require(sum(item.file_size for item in archive.infolist()) <= maximum, "Package is too large.")
        for item in archive.infolist():
            name = item.filename
            require(not name.startswith("/") and ".." not in PurePosixPath(name).parts and "\\" not in name
                    and (item.external_attr >> 16) & 0o170000 != 0o120000 and name not in result,
                    "Unsafe or duplicate package member.")
            if not item.is_dir():
                result[name] = archive.read(item)
    return result


def s3_location(item):
    url = urllib.parse.urlsplit(item["uri"])
    require(url.scheme == "s3" and url.netloc and url.path.startswith("/") and not url.query and not url.fragment,
            "Expected a versioned S3 artifact reference.")
    require(item.get("versionId") not in (None, "", "null"), "Artifact object is not versioned.")
    return url.netloc, url.path.lstrip("/")


def object_bytes(s3, item, account, limit=300 * 1024 * 1024):
    bucket, key = s3_location(item)
    response = s3.get_object(Bucket=bucket, Key=key, VersionId=item["versionId"], ExpectedBucketOwner=account)
    require(response.get("VersionId") == item["versionId"] and response.get("ContentLength", limit + 1) <= limit,
            "Artifact version/size differs from the release record.")
    try:
        content = response["Body"].read(limit + 1)
    finally:
        response["Body"].close()
    require(len(content) <= limit and sha(content) == item["sha256"], "Artifact checksum verification failed.")
    return content


def put_bytes(s3, bucket, key, data, account, **extra):
    digest = sha(data)
    response = s3.put_object(Bucket=bucket, Key=key, Body=data, ExpectedBucketOwner=account,
                             ServerSideEncryption="AES256", ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
                             Metadata={"sha256": digest}, **extra)
    require(response.get("VersionId") not in (None, "", "null"), "Registry uploads require S3 versioning.")
    return {"uri": "s3://" + bucket + "/" + key, "sha256": digest, "versionId": response["VersionId"]}


def put_content(s3, bucket, key, data, account):
    """Reuse the same immutable object version for identical bytes across releases."""
    try:
        old = s3.head_object(Bucket=bucket, Key=key, ExpectedBucketOwner=account)
    except Exception as error:
        if getattr(error, "response", {}).get("Error", {}).get("Code") not in {"NoSuchKey", "404", "NotFound"}:
            raise
    else:
        item = {"uri": "s3://" + bucket + "/" + key, "sha256": sha(data), "versionId": old.get("VersionId")}
        require(object_bytes(s3, item, account) == data, "Content-addressed artifact differs.")
        return item
    try:
        return put_bytes(s3, bucket, key, data, account, IfNoneMatch="*")
    except Exception as error:
        if getattr(error, "response", {}).get("Error", {}).get("Code") != "PreconditionFailed":
            raise
        old = s3.head_object(Bucket=bucket, Key=key, ExpectedBucketOwner=account)
        item = {"uri": "s3://" + bucket + "/" + key, "sha256": sha(data), "versionId": old.get("VersionId")}
        require(object_bytes(s3, item, account) == data, "Concurrent content-addressed upload differs.")
        return item


def template_url(item, region):
    bucket, key = s3_location(item)
    return (f"https://{bucket}.s3.{region}.amazonaws.com/" + urllib.parse.quote(key, safe="/")
            + "?versionId=" + urllib.parse.quote(item["versionId"], safe=""))


def verify_registry(session, bucket, account, region):
    require(session.client("sts").get_caller_identity()["Account"] == account, "Unexpected AWS account.")
    require(region == session.region_name, "Unexpected AWS region.")
    s3 = session.client("s3")
    s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
    location = s3.get_bucket_location(Bucket=bucket, ExpectedBucketOwner=account).get("LocationConstraint") or "us-east-1"
    require(location == region, "Artifact bucket region differs.")
    require(s3.get_bucket_versioning(Bucket=bucket, ExpectedBucketOwner=account).get("Status") == "Enabled",
            "Artifact bucket must have versioning enabled.")
    public = s3.get_public_access_block(Bucket=bucket, ExpectedBucketOwner=account)["PublicAccessBlockConfiguration"]
    require(all(public.get(key) for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")),
            "Artifact bucket must block all public access.")
    tags = {row["Key"]: row["Value"] for row in s3.get_bucket_tagging(Bucket=bucket, ExpectedBucketOwner=account)["TagSet"]}
    require(tags.get("navigan:environment") == "dev" and tags.get("navigan:purpose") == "release-artifacts",
            "Expected the dedicated DEV release registry.")


def pages(client, operation, key, **arguments):
    if hasattr(client, "can_paginate") and client.can_paginate(operation):
        return [row for page in client.get_paginator(operation).paginate(**arguments) for row in page.get(key, [])]
    result, token = [], None
    while True:
        response = getattr(client, operation)(**arguments, **({"NextToken": token} if token else {}))
        result.extend(response.get(key, []))
        token = response.get("NextToken")
        if not token:
            return result


def get_optional(s3, bucket, key, account):
    try:
        response = s3.get_object(Bucket=bucket, Key=key, ExpectedBucketOwner=account)
    except Exception as error:
        if getattr(error, "response", {}).get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return None
        raise
    try:
        value = json.loads(response["Body"].read(5 * 1024 * 1024))
    finally:
        response["Body"].close()
    return value, response.get("ETag"), response.get("VersionId")


def verify_image(session, component, item, account, region):
    repository = REGISTRY_PREFIX + "/" + component
    expected = f"{account}.dkr.ecr.{region}.amazonaws.com/{repository}@sha256:{item['sha256']}"
    require(item["uri"] == expected, "Image is outside the dedicated DEV release repositories.")
    details = session.client("ecr").describe_images(repositoryName=repository,
                                                   imageIds=[{"imageDigest": "sha256:" + item["sha256"]}])["imageDetails"]
    require(len(details) == 1 and details[0]["imageDigest"] == "sha256:" + item["sha256"], "Image digest was not found.")
    if component == "frontend":
        proof = item.get("runtimeConfigProof", {})
        require(proof.get("passed") is True and proof.get("configurations") == ["dev-fixture", "prod-fixture"]
                and proof.get("contract") == CONTRACT, "Same-image runtime configuration evidence is required.")
