#!/usr/bin/env python3
"""Read-only release planner. Does not build, upload, deploy, or execute SQL.

Build planning compares two explicit committed revisions and can reuse immutable
artifacts from an earlier manifest. Promotion compares manifests, never rebuilds.
Missing history, unknown paths and unclassified changes require review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "navigan-release-manifest-v1"
COMPONENTS = (
    "frontend", "backend", "infrastructure", "database", "cluster-connector",
    "migration-connector", "terraform-runner", "image-worker", "tools-gateway",
)
IMAGES = set(COMPONENTS) - {"backend", "infrastructure", "database"}
SCHEMA = re.compile(r"^database/migrations/[0-9]+_[A-Za-z0-9_-]+\.sql$")
SHA = re.compile(r"^[a-f0-9]{64}$")


def require(value, message):
    if not value:
        raise ValueError(message)


def git(*args, root=ROOT):
    return subprocess.check_output(["git", *args], cwd=root)


def revision(ref, root=ROOT):
    value = git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}", root=root).decode().strip()
    require(bool(re.fullmatch(r"[a-f0-9]{40,64}", value)), "Expected an exact commit revision.")
    return value


def changes(base, head, root=ROOT):
    require(subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=root,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0,
            "The baseline must be an ancestor of the candidate; fetch history or choose the correct baseline.")
    fields = git("diff", "--name-status", "-z", "--find-renames", base, head, "--", root=root).decode().split("\0")
    result = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        index += 1
        count = 2 if status[0] in "RC" else 1
        require(index + count <= len(fields) - 1, "Incomplete Git change record.")
        paths = fields[index:index + count]
        index += count
        require(status[0] in "AMDRCT", "Unsupported Git change status.")
        for path in paths:
            require(not path.startswith("/") and ".." not in PurePosixPath(path).parts and "\\" not in path,
                    "Unsupported repository path.")
        result.append({"status": status[0], "paths": paths})
    return result


def classify(path):
    """Artifact owners, validation families, and reason for a tracked input."""
    if path in {"AGENTS.md", "README.md", "LICENSE", ".gitignore", "frontend/README.md"} or path.endswith("/AGENTS.md"):
        return set(), set(), "documentation or repository metadata"
    if path in {"docs/openapi.json", "docs/environment-openapi.json"}:
        return set(), {"backend", "frontend", "api-contract"}, "API contract consumers"
    if path.startswith("docs/"):
        return set(), set(), "documentation"
    if path.startswith("frontend/tests/") or path.startswith("frontend/scripts/check-"):
        return set(), {"frontend"}, "frontend verification only"
    if path.startswith("frontend/"):
        return {"frontend"}, {"frontend"}, "frontend build input"
    if path.startswith("tests/"):
        return set(), {"backend"}, "backend verification only"
    if path.startswith("database/"):
        return {"database"}, {"database"}, "database scripts; execution is a separate stage"
    if path == "scripts/migrate.py":
        return {"database"}, {"database"}, "database migration executor"
    if path == "pyproject.toml":
        return {"backend"}, {"backend"}, "Python package/dependency definition"
    if path.startswith("src/"):
        # The current image-worker Dockerfile copies src/navigan and src/requirements.txt.
        return {"backend", "image-worker"}, {"backend"}, "Lambda source and image-worker build context"
    if path.startswith("platform/system-repo-template/"):
        return {"backend"}, {"backend", "template-consistency"}, "generated cluster bootstrap templates"
    if path.startswith(("provisioning/runner/", "terraform/modules/aws-eks/")):
        return {"terraform-runner"}, {"terraform"}, "runner image or embedded Terraform module"
    for prefix, component in (("connector/", "cluster-connector"), ("migration_connector/", "migration-connector"),
                              ("workspace_image_worker/", "image-worker"), ("tools-gateway/", "tools-gateway")):
        if path.startswith(prefix):
            return {component}, {"backend" if component != "tools-gateway" else "gateway"}, "container build input"
    if path.startswith("infrastructure/") or path == "samconfig.toml":
        return {"infrastructure"}, {"infrastructure"}, "infrastructure template/configuration"
    if path.startswith(("scripts/", ".github/workflows/")):
        return set(), {"release-tooling"}, "release/verification tooling; review execution-contract changes"
    return set(), set(), "UNCLASSIFIED"


def template_build_contract(content):
    """Infrastructure-only edits reuse ZIPs; runtime/build-contract edits do not."""
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def intrinsic(loader, tag, node):
        if isinstance(node, yaml.ScalarNode):
            value = loader.construct_scalar(node)
        elif isinstance(node, yaml.SequenceNode):
            value = loader.construct_sequence(node, deep=True)
        else:
            value = loader.construct_mapping(node, deep=True)
        return {tag: value}

    Loader.add_multi_constructor("!", intrinsic)
    documents = [value for value in yaml.load_all(content, Loader=Loader) if value is not None]
    require(all(isinstance(value, dict) for value in documents), "Infrastructure YAML must be a mapping.")
    if len(documents) > 1:
        require(not any(value.get("Globals", {}).get("Function") or any(
            item.get("Type") == "AWS::Serverless::Function" for item in value.get("Resources", {}).values()
        ) for value in documents), "SAM build templates must contain a single YAML document.")
        # Kubernetes bundles under infrastructure/ are not Lambda build inputs.
        return {"globals": {}, "functions": {}, "referencedParameters": {}}
    document = documents[0] if documents else {}
    require(isinstance(document, dict), "Infrastructure YAML must be a mapping.")
    keys = {"CodeUri", "Runtime", "Architectures", "Layers", "PackageType"}
    properties = lambda value: {key: value[key] for key in keys if key in value}
    result = {"globals": properties(document.get("Globals", {}).get("Function", {})), "functions": {}}
    for name, item in document.get("Resources", {}).items():
        if item.get("Type") == "AWS::Serverless::Function":
            result["functions"][name] = {"properties": properties(item.get("Properties", {})),
                                         "metadata": item.get("Metadata", {})}
    # Parameter defaults can influence an intrinsic Runtime/Architecture/build input.
    encoded = json.dumps(result, sort_keys=True)
    result["referencedParameters"] = {name: value for name, value in document.get("Parameters", {}).items()
                                       if json.dumps(name) in encoded}
    return result


def validate_manifest(value):
    require(isinstance(value, dict), "Expected a release manifest object.")
    require(value.get("format") == FORMAT and isinstance(value.get("sourceRevision"), str)
            and re.fullmatch(r"[a-f0-9]{40,64}", value["sourceRevision"]),
            "Invalid release manifest identity.")
    require(isinstance(value.get("components"), dict) and set(value["components"]) <= set(COMPONENTS),
            "Invalid component inventory.")
    for component, item in value["components"].items():
        require(isinstance(item, dict) and isinstance(item.get("inputHash"), str) and SHA.fullmatch(item["inputHash"])
                and isinstance(item.get("sha256"), str) and SHA.fullmatch(item["sha256"]), "Artifact checksums are required.")
        uri = item.get("uri", "")
        require(isinstance(uri, str), "Artifact references must be strings.")
        if component in IMAGES:
            require(bool(re.fullmatch(r"[A-Za-z0-9._:/-]+@sha256:" + item["sha256"], uri)),
                    "Container artifacts require an immutable digest reference.")
        else:
            require(bool(re.fullmatch(r"s3://[a-z0-9.-]+/[A-Za-z0-9._/-]+", uri))
                    and isinstance(item.get("versionId"), str) and item["versionId"] not in {"", "null"},
                    "Packaged artifacts require an S3 key, checksum and object version.")
        require(isinstance(item.get("portable"), bool), "Artifact portability must be explicit.")
    return value


def manifest(path):
    return validate_manifest(json.loads(Path(path).read_text()))


def blob(rev, path, root=ROOT):
    if not git("ls-tree", "-z", rev, "--", path, root=root):
        return b""
    return git("show", f"{rev}:{path}", root=root)


def input_hash(component, head, root=ROOT):
    entries = git("ls-tree", "-r", "-z", head, root=root).split(b"\0")
    selected = []
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        path = name.decode()
        owners, _, _ = classify(path)
        if component in owners:
            selected.append(metadata + b"\t" + name)
        if component == "backend" and path.startswith("infrastructure/") and path.endswith((".yaml", ".yml")):
            contract = template_build_contract(blob(head, path, root))
            if contract["globals"] or contract["functions"]:
                selected.append(name + b"\tbuild-contract:" + json.dumps(contract, sort_keys=True).encode())
    return hashlib.sha256(b"\0".join(sorted(selected))).hexdigest()


def build_plan(base, head, previous=None, root=ROOT):
    records = changes(base, head, root)
    owners, validations, reasons, review = set(), set(), {}, []
    for record in records:
        for path in record["paths"]:
            affected, checks, reason = classify(path)
            owners.update(affected)
            validations.update(checks)
            reasons[path] = {"components": sorted(affected), "validation": sorted(checks), "reason": reason}
            if reason == "UNCLASSIFIED":
                review.append({"path": path, "reason": "Add an impact rule before building/deploying."})
            if path.startswith("database/migrations/") and (record["status"] != "A" or not SCHEMA.fullmatch(path)):
                review.append({"path": path, "reason": "Applied migrations are immutable; existing edits/removals/renames require review."})
            if record["status"] == "T":
                review.append({"path": path, "reason": "File type changes require review."})
            if path.startswith("infrastructure/") and path.endswith((".yaml", ".yml")):
                before = blob(base, path, root)
                after = blob(head, path, root)
                if template_build_contract(before) != template_build_contract(after):
                    owners.add("backend")
                    validations.add("backend")
                    reasons[path]["components"] = sorted(set(reasons[path]["components"]) | {"backend"})
                    reasons[path]["reason"] += "; Lambda build/runtime inputs changed"
    if previous:
        validate_manifest(previous)
        require(previous["sourceRevision"] == base, "Manifest revision must match the selected build baseline.")
    reuse, builds, hashes = [], [], {}
    for component in COMPONENTS:
        digest = input_hash(component, head, root)
        hashes[component] = digest
        old = (previous or {}).get("components", {}).get(component)
        if old and old["inputHash"] == digest and component not in owners:
            reuse.append(component)
        elif component in owners:
            # A changed execution/build contract can require a new artifact even
            # when raw application files have the same hashes.
            builds.append(component)
    return {"format": "navigan-release-plan-v1", "mode": "build-plan", "baseRevision": base,
            "sourceRevision": head, "build": sorted(builds), "reuse": sorted(reuse),
            "skippedBuild": sorted(set(COMPONENTS) - set(builds)),
            "validation": sorted(validations), "inputHashes": hashes, "reasons": reasons,
            "reviewRequired": review, "readyForBuild": not review, "readyForDeployment": False,
            "deploymentPerformed": False,
            "notes": ["No baseline is inferred from HEAD~1 or the latest push.",
                      "This planner performs no build, AWS call, database migration or deployment.",
                      "A release manifest must retain unchanged artifact references.",
                      "Frontend build-time public configuration must be removed before cross-environment image promotion."]}


def promotion_plan(candidate, deployed, environment, config_hash, deployed_config_hash):
    validate_manifest(candidate)
    require(environment in {"dev", "prod"}, "Unknown deployment environment.")
    require(isinstance(config_hash, str) and isinstance(deployed_config_hash, str)
            and SHA.fullmatch(config_hash) and SHA.fullmatch(deployed_config_hash), "Explicit environment configuration hashes required.")
    require(isinstance(deployed, dict), "Expected a deployment record object.")
    require(deployed.get("environment") == environment and deployed.get("status") == "SUCCEEDED",
            "Use the selected environment's last successful deployment record.")
    old = validate_manifest(deployed.get("manifest", {}))
    require(deployed_config_hash == deployed.get("configurationHash"), "Configuration baseline must match the deployment record.")
    missing = sorted(set(old["components"]) - set(candidate["components"]))
    require(not missing, "Candidate must retain unchanged components; removals require an explicit retirement plan.")
    selected, review = [], []
    for name, item in candidate["components"].items():
        identity = lambda artifact: {key: artifact.get(key) for key in ("uri", "sha256", "versionId")}
        if name not in old["components"] or identity(item) != identity(old["components"][name]):
            selected.append(name)
            if not item.get("portable"):
                review.append({"component": name, "reason": "Artifact contains environment-specific build configuration."})
        elif config_hash != deployed_config_hash and not item.get("portable"):
            review.append({"component": name, "reason": "Changed environment configuration requires review of this non-portable artifact."})
    return {"format": "navigan-release-plan-v1", "mode": "promotion-plan", "environment": environment,
            "sourceRevision": candidate["sourceRevision"], "build": [], "publish": [],
            "deploy": sorted(selected), "configurationChanged": config_hash != deployed_config_hash,
            "reuse": sorted(set(candidate["components"]) - set(selected)),
            "reviewRequired": review, "readyForDeployment": False, "deploymentPerformed": False,
            "notes": ["Promotion reuses the recorded immutable artifacts; it never rebuilds.",
                      "Live target, configuration, migration and change-set checks remain deployment-executor responsibilities."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Exact last release revision, not the previous push")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--baseline-manifest", type=Path)
    parser.add_argument("--promote-manifest", type=Path)
    parser.add_argument("--deployment-record", type=Path)
    parser.add_argument("--environment", choices=["dev", "prod"])
    parser.add_argument("--config-hash")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.promote_manifest:
        require(not args.base and not args.baseline_manifest and args.deployment_record and args.environment and args.config_hash,
                "Promotion requires a candidate manifest, environment, last deployment record and configuration hash.")
        candidate = manifest(args.promote_manifest)
        deployed = json.loads(args.deployment_record.read_text())
        # Validate the embedded deployed manifest through the same immutable rules.
        validate_manifest(deployed.get("manifest", {}))
        result = promotion_plan(candidate, deployed, args.environment, args.config_hash, deployed.get("configurationHash", ""))
    else:
        require(not args.deployment_record and not args.environment and not args.config_hash,
                "Deployment inputs are only accepted for promotion planning.")
        previous = manifest(args.baseline_manifest) if args.baseline_manifest else None
        require(args.base or previous, "Supply --base or --baseline-manifest; a deployed baseline is never guessed.")
        base = revision(args.base or previous["sourceRevision"])
        result = build_plan(base, revision(args.head), previous)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    return 2 if result["reviewRequired"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, subprocess.CalledProcessError, OSError, json.JSONDecodeError):
        raise SystemExit("Release planning stopped. Check the explicit baseline, manifest and repository paths; no deployment was performed.") from None
