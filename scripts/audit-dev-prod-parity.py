#!/usr/bin/env python3
"""Read-only AWS inventory for restoring DEV parity. Never deploys or copies data.

Prints JSON to stdout. No environment values, secret contents, or download URLs
are printed. A successful inventory is NOT a declaration of functional parity.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ACCOUNT = "905418045935"
REGION = "ap-south-1"
PARENTS = {"dev": "navigan-ashok-dev", "prod": "navigan-custmanagement-cfnstk"}
BRANCH = "new_migration_approach_18oct26"
ROOT = Path(__file__).resolve().parents[1]


def fingerprint(value):
    return hashlib.sha256(value).hexdigest()


def error_code(error):
    # AWS messages can contain operational details: retain codes only.
    return getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)


def package_hashes(data):
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        names = package.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP members")
        return {name: fingerprint(package.read(name)) for name in sorted(names)
                if name.startswith("navigan/") and name.endswith(".py")}


def compare_functions(dev, prod):
    result = {}
    for key in sorted(set(dev) | set(prod)):
        d, p = dev.get(key), prod.get(key)
        if not d or not p:
            result[key] = {"status": "missing-dev" if not d else "missing-prod"}
            continue
        dh, ph = d.get("sourceHashes"), p.get("sourceHashes")
        source = "unverified" if not dh or not ph else "match" if dh == ph else "different"
        result[key] = {
            "source": source,
            "differentFiles": sorted(k for k in set(dh or {}) | set(ph or {})
                                     if (dh or {}).get(k) != (ph or {}).get(k)),
            "packageChecksumMatches": d["codeSha256"] == p["codeSha256"],
            "runtimeMatches": all(d.get(k) == p.get(k) for k in ("runtime", "architectures", "handler", "layers")),
            "environmentKeysOnlyDev": sorted(set(d["environmentKeys"]) - set(p["environmentKeys"])),
            "environmentKeysOnlyProd": sorted(set(p["environmentKeys"]) - set(d["environmentKeys"])),
            "sourceFirstMatches": d["sourceFirst"] == p["sourceFirst"],
        }
    return result


def inventory(session, parent, include_source):
    cfn = session.client("cloudformation")
    lam = session.client("lambda")
    result = {"parent": parent, "stacks": {}, "functions": {}, "apis": {}, "services": {}, "errors": []}
    seen = set()

    def visit(stack, prefix=""):
        if stack in seen:
            return
        seen.add(stack)
        try:
            desc = cfn.describe_stacks(StackName=stack)["Stacks"][0]
            result["stacks"][prefix or "root"] = {"name": desc["StackName"], "status": desc["StackStatus"]}
            resources = [r for page in cfn.get_paginator("list_stack_resources").paginate(StackName=stack)
                         for r in page["StackResourceSummaries"]]
        except Exception as error:
            result["errors"].append({"resource": prefix or parent, "code": error_code(error)})
            return
        for r in resources:
            name, kind = r.get("PhysicalResourceId"), r["ResourceType"]
            key = prefix + r["LogicalResourceId"]
            if not name or r.get("ResourceStatus") == "DELETE_COMPLETE":
                continue
            try:
                if kind == "AWS::CloudFormation::Stack":
                    visit(name, key + "/")
                elif kind == "AWS::Lambda::Function":
                    response = lam.get_function(FunctionName=name)
                    cfg = response["Configuration"]
                    env = cfg.get("Environment", {}).get("Variables", {})
                    item = {"name": name, "codeSha256": cfg["CodeSha256"],
                            "runtime": cfg.get("Runtime"), "handler": cfg.get("Handler"),
                            "architectures": cfg.get("Architectures", []),
                            "layers": [v["Arn"] for v in cfg.get("Layers", [])],
                            "state": cfg.get("State"), "lastUpdate": cfg.get("LastUpdateStatus"),
                            "database": env.get("DB_NAME") if env.get("DB_NAME") in ("navigan", "navigan_dev") else "unverified",
                            "sourceFirst": env.get("MIGRATION_SOURCE_FIRST_ENABLED") if env.get("MIGRATION_SOURCE_FIRST_ENABLED") in (None, "true", "false") else "unrecognized",
                            "environmentKeys": sorted(env)}
                    result["functions"][key] = item
                    if include_source and cfg.get("PackageType", "Zip") == "Zip":
                        with urllib.request.urlopen(response["Code"]["Location"], timeout=60) as stream:
                            raw = stream.read()
                        import base64
                        if base64.b64encode(hashlib.sha256(raw).digest()).decode() != cfg["CodeSha256"]:
                            raise ValueError("Package checksum mismatch")
                        item["sourceHashes"] = package_hashes(raw)
                elif kind == "AWS::ApiGatewayV2::Api":
                    api = session.client("apigatewayv2")
                    routes, token = [], None
                    while True:
                        page = api.get_routes(ApiId=name, **({"NextToken": token} if token else {}))
                        routes.extend({"route": x["RouteKey"], "auth": x.get("AuthorizationType"),
                                       "hasAuthorizer": bool(x.get("AuthorizerId")),
                                       "scopes": sorted(x.get("AuthorizationScopes", [])),
                                       "hasTarget": bool(x.get("Target"))} for x in page.get("Items", []))
                        token = page.get("NextToken")
                        if not token:
                            break
                    result["apis"][key] = {"id": name, "routes": sorted(routes, key=lambda x: x["route"])}
                elif kind == "AWS::ECS::Service":
                    # An ARN supplies the exact cluster, avoiding guessed cluster names.
                    parts = name.split("/")
                    if len(parts) < 3 or ":service/" not in name:
                        result["errors"].append({"resource": key, "code": "EcsClusterUnresolved"})
                        continue
                    ecs = session.client("ecs")
                    response = ecs.describe_services(cluster=parts[-2], services=[name])
                    if response.get("failures") or len(response.get("services", [])) != 1:
                        raise ValueError("ECS service missing")
                    svc = response["services"][0]
                    task = ecs.describe_task_definition(taskDefinition=svc["taskDefinition"])["taskDefinition"]
                    result["services"][key] = {"task": svc["taskDefinition"], "desired": svc["desiredCount"],
                        "running": svc["runningCount"], "pending": svc["pendingCount"],
                        "rollouts": [d.get("rolloutState") for d in svc.get("deployments", [])],
                        "containers": [{"name": c["name"], "image": c["image"],
                                        "environmentKeys": sorted(e["name"] for e in c.get("environment", []))}
                                       for c in task["containerDefinitions"]]}
            except Exception as error:
                result["errors"].append({"resource": key, "code": error_code(error)})

    visit(parent)
    for suffix in ("artifact-workspace", "workspace-repositories", "workspace-image-runtime", "workspace-images"):
        visit(parent + "-" + suffix, suffix + "/")
    if parent == PARENTS["prod"]:
        visit("navigan-frontend", "frontend/")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--include-source", action="store_true", help="Download Lambda ZIPs into memory and compare application source hashes")
    args = parser.parse_args()
    import boto3
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise SystemExit("Unexpected AWS account; no inventory performed")
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != BRANCH:
        raise SystemExit("Use the existing " + BRANCH + " checkout")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    environments = {label: inventory(session, parent, args.include_source) for label, parent in PARENTS.items()}
    dev, prod = environments["dev"], environments["prod"]
    report = {"format": 1, "observedAt": datetime.now(timezone.utc).isoformat(), "revision": revision,
              "parity": "UNVERIFIED", "environments": environments,
              "functionComparison": compare_functions(dev["functions"], prod["functions"]),
              "limits": ["Read-only inventory; no cloud writes or data copy.",
                         "Route presence/auth flags do not prove integration target correctness.",
                         "Environment values, IAM/trust, storage settings and database schemas/grants require separate checks.",
                         "ECS task images do not prove running image digest or local DEV frontend version.",
                         "Authenticated workflow smoke tests remain required; errors mean incomplete evidence."]}
    print(json.dumps(report, indent=2))
    return 2 if any(e["errors"] for e in environments.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
