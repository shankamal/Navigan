#!/usr/bin/env python3
"""Discover approved DEV Retailflow images through SSM and mirror them to private ECR."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

ACCOUNT = "905418045935"
REGION = "ap-south-1"
INSTANCE = "i-08e28d9b2242cbd53"
REGISTRY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"
# The SSM output contains only image references and node architectures, never Pod bodies.
DISCOVER = r"""
import json, subprocess
base = ["sudo", "kubectl", "--kubeconfig", "/etc/kubernetes/admin.conf"]
objects = json.loads(subprocess.check_output(base + ["-n", "retailflow", "get", "deployments,statefulsets,daemonsets,jobs,cronjobs,pods", "-o", "json"], text=True))
images = set()
for obj in objects.get("items", []):
    spec = obj.get("spec") or {}
    if obj.get("kind") == "CronJob":
        spec = (spec.get("jobTemplate") or {}).get("spec") or {}
    if obj.get("kind") != "Pod":
        spec = (spec.get("template") or {}).get("spec") or {}
    for field in ("containers", "initContainers"):
        for container in spec.get(field, []):
            if container.get("image"):
                images.add(container["image"])
nodes = json.loads(subprocess.check_output(base + ["get", "nodes", "-o", "json"], text=True))
architectures = sorted({n.get("status", {}).get("nodeInfo", {}).get("architecture") for n in nodes.get("items", [])} - {None})
print(json.dumps({"namespace": "retailflow", "images": sorted(images), "architectures": architectures}))
"""


class CommandError(RuntimeError):
    pass


def run(command, *, input=None):
    result = subprocess.run(command, input=input, text=True, capture_output=True)
    if result.returncode:
        # Authentication output is never included in errors.
        if "login" in command or "get-login-password" in command:
            raise CommandError("ECR authentication failed; check the navigan AWS profile and Docker daemon.")
        raise CommandError(result.stderr.strip() or f"Command failed: {command[0]}")
    return result.stdout


def source_identity(reference):
    """Canonicalize OCI references without inventing an application image name."""
    if not isinstance(reference, str) or len(reference) > 1000 or any(c.isspace() for c in reference):
        raise ValueError("Invalid source image reference.")
    base, separator, digest = reference.partition("@")
    if separator and not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Only SHA-256 image digest references are supported.")
    first, slash, remainder = base.partition("/")
    if slash and ("." in first or ":" in first or first == "localhost"):
        host, repository = first, remainder
    else:
        host, repository = "docker.io", base
    if host in {"index.docker.io", "registry-1.docker.io"}:
        host = "docker.io"
    if ":" in repository.rsplit("/", 1)[-1]:
        repository, tag = repository.rsplit(":", 1)
    else:
        tag = "latest"
    if host == "docker.io" and "/" not in repository:
        repository = "library/" + repository
    if not re.fullmatch(r"[a-z0-9][a-z0-9.:-]*", host) or not re.fullmatch(
        r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", repository
    ):
        raise ValueError("Source image registry/repository is invalid.")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
        raise ValueError("Source image tag is invalid.")
    canonical = f"{host}/{repository}" + ("@" + digest if separator else ":" + tag)
    # Keeping the original registry/organization prevents collisions between upstream images.
    destination = "retailflow/" + host.replace(":", "-") + "/" + repository
    if len(destination) > 256:
        raise ValueError("Destination ECR repository name exceeds 256 characters.")
    return {"source": canonical, "repository": destination, "sourceTag": tag if not separator else "digest"}


def snapshot_tag(source_tag, image_id):
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
        raise ValueError("Docker did not report a SHA-256 image identity.")
    return source_tag[:40] + "-amd64-" + image_id.removeprefix("sha256:")[:24]


def aws_command(profile, *parts):
    output = run(["aws", "--profile", profile, "--region", REGION, "--output", "json", *parts])
    return json.loads(output) if output.strip() else {}


def discover(aws):
    import base64

    encoded = base64.b64encode(DISCOVER.encode()).decode()
    with tempfile.TemporaryDirectory(prefix="navigan-retailflow-inventory-") as temporary:
        parameters = Path(temporary) / "parameters.json"
        parameters.write_text(
            json.dumps({"commands": [f"python3 -c \"import base64; exec(base64.b64decode('{encoded}'))\""]})
        )
        command_id = aws(
            "ssm",
            "send-command",
            "--instance-ids",
            INSTANCE,
            "--document-name",
            "AWS-RunShellScript",
            "--comment",
            "Read DEV Retailflow image references only",
            "--parameters",
            "file://" + str(parameters),
        )["Command"]["CommandId"]
        print(f"Reading Retailflow image references through SSM: {command_id}", flush=True)
        for _ in range(90):
            time.sleep(2)
            try:
                result = aws(
                    "ssm", "get-command-invocation", "--command-id", command_id, "--instance-id", INSTANCE
                )
            except CommandError as error:
                if "InvocationDoesNotExist" in str(error):
                    continue
                raise
            if result["Status"] == "Success":
                inventory = json.loads(result["StandardOutputContent"].strip())
                if inventory.get("namespace") != "retailflow" or not inventory.get("images"):
                    raise ValueError("No Retailflow images were discovered; nothing will be pushed.")
                if inventory.get("architectures") != ["amd64"]:
                    raise ValueError(
                        "This DEV copier supports the approved amd64 lab only; mixed/other architectures need a multi-architecture copy."
                    )
                return sorted({source_identity(image)["source"] for image in inventory["images"]})
            if result["Status"] not in {"Pending", "InProgress", "Delayed"}:
                raise CommandError(
                    "Read-only Retailflow discovery failed: "
                    + result["Status"]
                    + ". Check SSM command "
                    + command_id
                )
    raise CommandError("Retailflow discovery timed out; check SSM command " + command_id)


def ensure_repository(aws, repository):
    try:
        return aws("ecr", "describe-repositories", "--repository-names", repository)["repositories"][0]
    except CommandError as error:
        if "RepositoryNotFoundException" not in str(error):
            raise
    return aws(
        "ecr",
        "create-repository",
        "--repository-name",
        repository,
        "--image-tag-mutability",
        "IMMUTABLE",
        "--image-scanning-configuration",
        "scanOnPush=true",
        "--tags",
        "Key=Application,Value=Retailflow",
        "Key=Environment,Value=DEV",
    )["repository"]


def platform_reference(docker, source):
    """Resolve the architecture before touching Docker's local image store."""
    descriptor = json.loads(docker([
        "docker", "buildx", "imagetools", "inspect", "--format", "{{json .Manifest}}", source,
    ]))
    if isinstance(descriptor.get("manifests"), list):
        candidates = [
            item for item in descriptor["manifests"]
            if item.get("platform", {}).get("os") == "linux"
            and item.get("platform", {}).get("architecture") == "amd64"
            and item.get("platform", {}).get("variant", "") in {"", "v1"}
        ]
        if len(candidates) != 1:
            raise ValueError("Source manifest does not identify exactly one linux/amd64 image; copy stopped.")
        digest = candidates[0].get("digest", "")
    else:
        digest = descriptor.get("digest", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Source manifest digest is invalid; copy stopped.")
    repository = source.split("@", 1)[0]
    if ":" in repository.rsplit("/", 1)[-1]:
        repository = repository.rsplit(":", 1)[0]
    return repository + "@" + digest


def mirror(aws, images, *, docker=run):
    # Docker already holds any source registry credentials configured by the user.
    password = aws("ecr", "get-authorization-token")["authorizationData"][0]
    import base64

    credentials = base64.b64decode(password["authorizationToken"]).decode()
    username, secret = credentials.split(":", 1)
    if password.get("proxyEndpoint") != "https://" + REGISTRY or username != "AWS":
        raise ValueError("ECR authentication endpoint does not match the approved DEV registry.")
    docker(["docker", "login", "--username", username, "--password-stdin", REGISTRY], input=secret + "\n")
    mappings = []
    for image in images:
        identity = source_identity(image)
        if image.startswith(REGISTRY + "/"):
            mappings.append({"source": image, "destination": image, "status": "ALREADY_IN_ECR"})
            continue
        print("Copying " + identity["source"], flush=True)
        pinned = platform_reference(docker, identity["source"])
        print("  Pinned linux/amd64 source: " + pinned, flush=True)
        # Pull the child digest directly. --platform on a multi-platform tag can
        # leave broken platform metadata in the containerd image store.
        docker(["docker", "pull", pinned])
        inspected = json.loads(
            docker(["docker", "image", "inspect", "--format", "{{json .}}", pinned])
        )
        if inspected.get("Architecture") != "amd64" or inspected.get("Os") != "linux":
            raise ValueError("Pulled image platform does not match the source lab.")
        tag = snapshot_tag(identity["sourceTag"], inspected["Id"])
        repository = ensure_repository(aws, identity["repository"])
        expected_uri = REGISTRY + "/" + identity["repository"]
        if repository["repositoryUri"] != expected_uri:
            raise ValueError("ECR repository identity mismatch.")
        target = expected_uri + ":" + tag
        try:
            existing = aws(
                "ecr",
                "describe-images",
                "--repository-name",
                identity["repository"],
                "--image-ids",
                "imageTag=" + tag,
            )["imageDetails"]
        except CommandError as error:
            if "ImageNotFoundException" not in str(error):
                raise
            existing = []
        if not existing:
            # Tag the pinned manifest reference, not an index or config ID.
            # Docker IDs have different meanings across image-store backends.
            docker(["docker", "tag", pinned, target])
            docker(["docker", "push", target])
            existing = aws(
                "ecr",
                "describe-images",
                "--repository-name",
                identity["repository"],
                "--image-ids",
                "imageTag=" + tag,
            )["imageDetails"]
        if not existing:
            raise ValueError("ECR did not confirm the pushed image.")
        digest = existing[0]["imageDigest"]
        mappings.append(
            {
                "source": identity["source"],
                "sourceResolvedReferences": [pinned],
                "destination": target,
                "destinationDigestReference": expected_uri + "@" + digest,
                "platform": "linux/amd64",
                "status": "AVAILABLE",
            }
        )
        print("  ECR: " + target, flush=True)
    return mappings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument(
        "--apply", action="store_true", help="Create ECR repositories and push all discovered images."
    )
    parser.add_argument(
        "--report",
        default="retailflow-ecr-images.json",
        help="Local mapping report; contains image references, no credentials.",
    )
    args = parser.parse_args()
    branch = run(["git", "branch", "--show-current"]).strip()
    if branch != "new_migration_approach_18oct26":
        raise SystemExit("Run this from the new_migration_approach_18oct26 DEV checkout.")

    def aws(*parts):
        return aws_command(args.profile, *parts)

    if aws("sts", "get-caller-identity").get("Account") != ACCOUNT:
        raise SystemExit("Unexpected AWS account; no source discovery or push was started.")
    images = discover(aws)
    print(f"Discovered {len(images)} unique images. ECR destination: {REGISTRY}")
    for image in images:
        identity = source_identity(image)
        print(
            identity["source"]
            + " -> "
            + (
                "already references this ECR registry"
                if image.startswith(REGISTRY + "/")
                else REGISTRY + "/" + identity["repository"]
            )
        )
    if not args.apply:
        print(
            "Review complete. Add --apply to mirror the linux/amd64 images. Source Kubernetes workloads are not changed."
        )
        return
    docker_os = json.loads(run(["docker", "version", "--format", "{{json .Server.Os}}"]))
    if docker_os != "linux":
        raise SystemExit("A running Linux Docker daemon is required.")
    mappings = mirror(aws, images)
    report = Path(args.report).resolve()
    report.write_text(
        json.dumps(
            {
                "accountId": ACCOUNT,
                "region": REGION,
                "sourceNamespace": "retailflow",
                "registry": REGISTRY,
                "images": mappings,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Verified ECR image references saved to {report}")
    print("Images copied. Running workloads, manifests, ConfigMaps and Secrets were not changed.")


if __name__ == "__main__":
    try:
        main()
    except (CommandError, ValueError, FileNotFoundError) as error:
        raise SystemExit(str(error)) from None
