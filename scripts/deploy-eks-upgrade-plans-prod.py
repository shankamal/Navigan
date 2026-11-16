#!/usr/bin/env python3
"""Prepare or execute the scoped PROD backend release for governed EKS plans.

The database migration and customer-role execution policy are separate, explicit
prerequisites. This release changes only the existing ClusterFunction package
and six JWT-protected upgrade routes. It never invokes an EKS update API.
"""

from __future__ import annotations

import argparse
import ast
import base64
import copy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import uuid
import zipfile

import boto3


ROOT = Path(__file__).resolve().parents[1]
BASELINE_TREE = "64be8680772f165939d738a0d7dd9abaf60341e4"
# PROD backend was last reconciled and deployed from the reviewed release below.
# Keep all deployed modules pinned together before replacing scoped plan code.
DEPLOYED_PLAN_TREE = "a8d572439b8f5097a48a86c442955afafd19f097"
DEPLOYED_UTILITY_TREE = "82deeec6bc0e2663420537462712bfe850b358bd"
FORMAT = "navigan-eks-upgrade-plans-prod-v1"
UTILITY_YAML_URL = "https://files.pythonhosted.org/packages/b9/2b/614b4752f2e127db5cc206abc23a8c19678e92b23c3db30fc86ab731d3bd/PyYAML-6.0.2-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
UTILITY_YAML_SHA = "80bab7bfc629882493af4aa31a4cfa43a4c57c83813253626916b8c7ada83476"
ROUTES = {
    "ClusterUpgradeOptionsRoute": "GET /api/v1/clusters/{clusterId}/upgrade-options",
    "ClusterUtilityUpgradeOptionsRoute": "GET /api/v1/clusters/{clusterId}/utility-upgrade-options",
    "ListClusterUpgradePlansRoute": "GET /api/v1/clusters/{clusterId}/upgrade-plans",
    "CreateClusterUpgradePlanRoute": "POST /api/v1/clusters/{clusterId}/upgrade-plans",
    "GetClusterUpgradePlanRoute": "GET /api/v1/clusters/{clusterId}/upgrade-plans/{planId}",
    "ClusterUpgradePlanActionRoute": "POST /api/v1/clusters/{clusterId}/upgrade-plans/{planId}/{upgradeAction}",
}


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load("upgrade_plan_readiness_support", "deploy-eks-upgrade-readiness-prod.py")
summary = base.summary
support = base.support
ACCOUNT, REGION, PARENT = base.ACCOUNT, base.REGION, base.PARENT
require = base.require


def digest(value):
    return hashlib.sha256(value).hexdigest()


def code_hash(value):
    return base64.b64encode(hashlib.sha256(value).digest()).decode()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, default=str))


def git_source(tree, path):
    return subprocess.check_output(["git", "show", f"{tree}:{path}"], cwd=ROOT)


def semantic(source):
    return ast.dump(ast.parse(source.decode()), include_attributes=False)


def normalized_semantic(source):
    # Compare the same canonical source representation used by the read-only
    # production diff. Reparse it to retain checks on operations, literals,
    # branches and names rather than comparing source layout/parser artifacts.
    canonical = ast.unparse(ast.parse(source.decode()))
    return semantic(canonical.encode("utf-8"))


def retry_response_handler(source):
    """Preserve the exact production-observed retry HTTP response classification.

    This does not add retry to routing, validation or execution permissions.
    Every other AST node is still checked against the pinned baseline.
    """
    original = b'status = 202 if parts[3] in {"execute", "refresh", "continue", "reconcile", "refresh-reconciliation", "apply-reconciliation"} else 200'
    reviewed = b'status = 202 if parts[3] in {"execute", "refresh", "continue", "retry", "reconcile", "refresh-reconciliation", "apply-reconciliation"} else 200'
    if source.count(reviewed) == 1 and original not in source:
        return source
    require(source.count(original) == 1 and reviewed not in source,
            "Unexpected upgrade-action HTTP response contract")
    return source.replace(original, reviewed, 1)


def replace_once(source, before, after, label):
    require(source.count(before) == 1, "Unexpected " + label + " contract")
    return source.replace(before, after, 1)


def utility_query_handler(source):
    """Patch only the reviewed query parser and utility-options call in live code."""
    prefix = "src/navigan/modules/cluster_management/handler.py"
    original = git_source(DEPLOYED_UTILITY_TREE, prefix)
    current = (ROOT / prefix).read_bytes()
    old_tree, new_tree = ast.parse(original), ast.parse(current)
    old_query = next(n for n in old_tree.body if isinstance(n, ast.FunctionDef) and n.name == "query_of")
    new_query = next(n for n in new_tree.body if isinstance(n, ast.FunctionDef) and n.name == "query_of")
    old_function = ast.get_source_segment(original.decode(), old_query)
    new_function = ast.get_source_segment(current.decode(), new_query)
    old_call = 'query_of(event).get("utility", "").lower()'
    new_call = 'query_of(event, allow_utility=True).get("utility", "").lower()'
    # Accept the canonical formatting used in the user's live-module comparisons.
    source_text = source.decode()
    live_tree = ast.parse(source_text)
    live_query = next(n for n in live_tree.body if isinstance(n, ast.FunctionDef) and n.name == "query_of")
    if ast.dump(live_query) == ast.dump(new_query):
        require(new_call in source_text or ast.unparse(ast.parse(new_call)) in source_text,
                "Utility query call is not patched")
        return source
    require(ast.dump(live_query) == ast.dump(old_query), "Unreviewed query validator")
    source_text = source_text.replace(ast.get_source_segment(source_text, live_query), new_function, 1)
    # Locate the call semantically so production quote/layout differences are safe.
    expected_call = ast.dump(ast.parse(old_call, mode="eval").body)
    matches = [n for n in ast.walk(ast.parse(source_text)) if isinstance(n, ast.Call) and ast.dump(n) == expected_call]
    require(len(matches) == 1, "Unexpected utility options query call")
    old_segment = ast.get_source_segment(source_text, matches[0])
    result = source_text.replace(old_segment, new_call, 1).encode()
    # Reverse only these two edits and check every unrelated AST node.
    reversed_text = result.decode().replace(new_function, old_function, 1).replace(new_call, old_call, 1)
    require(semantic(reversed_text.encode()) == semantic(source), "Unrelated handler change rejected")
    return result


def deployed_handler_baseline(source):
    """Reproduce the exact reviewed handler shape currently deployed in PROD."""
    replacements = (
        (b"    ConnectorUpgradeRequest,\n", b"", "connector model import"),
        (
            b'    upgrade_connector = (\n        method == "POST" and len(parts) == 3\n'
            b'        and parts[1:] == ["connector", "upgrade"]\n    )\n',
            b"",
            "connector route selector",
        ),
        (b"        or upgrade_connector\n", b"", "connector write selector"),
        (
            b"            else ConnectorUpgradeRequest\n            if upgrade_connector\n",
            b"",
            "connector request model",
        ),
        (
            b"        if upgrade_connector:\n"
            b'            access.require("cluster.access.manage")\n'
            b"            operation = method + \" \" + path\n"
            b"            fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(\",\", \":\")).encode()).hexdigest()\n"
            b"            customer_repo = CustomerRepository(db, principal)\n"
            b"            replay = customer_repo.idempotency_get(operation, key, fingerprint)\n"
            b"            if replay:\n"
            b'                result = response(replay["status"], replay["body"], correlation)\n'
            b'                result["headers"]["Idempotency-Replayed"] = "true"\n'
            b"                return result\n"
            b"            value = repo.upgrade_connector_gitops(identifier, body)\n"
            b'            customer_repo.idempotency_put(operation, key, fingerprint, {"status": 202, "body": value})\n'
            b"            return response(202, value, correlation)\n",
            b"",
            "connector upgrade handler",
        ),
    )
    for before, after, label in replacements:
        source = replace_once(source, before, after, label)
    repository_imports = (
        b"from .bootstrap_status import refresh_installer_status\n"
        b"from .tool_access import resolve_tool_access\n"
        b"from .upgrade_readiness import EksUpgradeDiscovery\n"
    )
    deployed_imports = (
        b"from .tool_access import resolve_tool_access\n"
        b"from .upgrade_readiness import EksUpgradeDiscovery\n"
        b"from .bootstrap_status import refresh_installer_status\n"
    )
    source = replace_once(source, repository_imports, deployed_imports, "readiness import order")
    repository_summary = (
        b'    if path != BASE and not path.startswith(BASE + "/"):\n'
        b'        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")\n'
        b'    parts = path[len(BASE):].strip("/").split("/") if path != BASE else []\n'
        b'    if parts == ["summary"]:\n'
        b'        if method != "GET":\n'
        b'            raise ApiError(405, "METHOD_NOT_ALLOWED", "Method not supported for this endpoint.")\n'
        b"        with transaction() as db:\n"
        b'            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")\n'
        b"            return response(200, Repository(db, principal).summary(), correlation)\n"
    )
    deployed_summary = (
        b'    if path == BASE + "/summary":\n'
        b'        if method != "GET":\n'
        b'            raise ApiError(405, "METHOD_NOT_ALLOWED", "Method not supported for this endpoint.")\n'
        b"        with transaction() as db:\n"
        b'            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")\n'
        b"            return response(200, Repository(db, principal).summary(), correlation)\n"
        b'    if path != BASE and not path.startswith(BASE + "/"):\n'
        b'        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")\n'
        b'    parts = path[len(BASE):].strip("/").split("/") if path != BASE else []\n'
    )
    return replace_once(source, repository_summary, deployed_summary, "summary route order")


def scoped_handler_target(source):
    """Remove the unrelated connector-upgrade increment from the reviewed plan handler."""
    replacements = (
        (b"    ConnectorUpgradeRequest,\n", b"", "target connector model import"),
        (
            b'    upgrade_connector = method == "POST" and len(parts) == 3 and parts[1:] == ["connector", "upgrade"]\n',
            b"",
            "target connector route selector",
        ),
        (b"        or upgrade_connector\n", b"", "target connector write selector"),
        (
            b"            else ConnectorUpgradeRequest\n            if upgrade_connector\n",
            b"",
            "target connector request model",
        ),
        (
            b"        if upgrade_connector:\n"
            b'            access.require("cluster.access.manage")\n'
            b"            operation = method + \" \" + path\n"
            b"            fingerprint = hashlib.sha256(\n"
            b'                json.dumps(body, sort_keys=True, separators=(",", ":")).encode()\n'
            b"            ).hexdigest()\n"
            b"            customer_repo = CustomerRepository(db, principal)\n"
            b"            replay = customer_repo.idempotency_get(operation, key, fingerprint)\n"
            b"            if replay:\n"
            b'                result = response(replay["status"], replay["body"], correlation)\n'
            b'                result["headers"]["Idempotency-Replayed"] = "true"\n'
            b"                return result\n"
            b"            value = repo.upgrade_connector_gitops(identifier, body)\n"
            b'            customer_repo.idempotency_put(operation, key, fingerprint, {"status": 202, "body": value})\n'
            b"            return response(202, value, correlation)\n",
            b"",
            "target connector upgrade handler",
        ),
    )
    for before, after, label in replacements:
        source = replace_once(source, before, after, label)
    plan_imports = (b"from .upgrade_plans import CreateEksUpgradePlan, EksUpgradePlans, UpgradePlanAction\n"
        if b"from .upgrade_paths import" not in source else
        b"from .upgrade_plans import CreateEksUpgradePlan, EksUpgradePlans\n"
        b"from .upgrade_paths import CreateScopedUpgradePlan, ScopedUpgradePlanAction as UpgradePlanAction, ScopedEksUpgradePlans\n")
    repository_imports = (
        b"from .bootstrap_status import refresh_installer_status\n"
        b"from .tool_access import resolve_tool_access\n"
        b"from .upgrade_readiness import EksUpgradeDiscovery\n"
        + plan_imports
    )
    deployed_imports = (
        b"from .tool_access import resolve_tool_access\n"
        b"from .upgrade_readiness import EksUpgradeDiscovery\n"
        + plan_imports + b"from .bootstrap_status import refresh_installer_status\n"
    )
    source = replace_once(
        source, repository_imports, deployed_imports, "target readiness import order"
    )
    repository_summary = (
        b'    if path != BASE and not path.startswith(BASE + "/"):\n'
        b'        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")\n'
        b'    parts = path[len(BASE) :].strip("/").split("/") if path != BASE else []\n'
        b'    if parts == ["summary"]:\n'
        b'        if method != "GET":\n'
        b'            raise ApiError(405, "METHOD_NOT_ALLOWED", "Method not supported for this endpoint.")\n'
        b"        with transaction() as db:\n"
        b'            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")\n'
        b"            return response(200, Repository(db, principal).summary(), correlation)\n"
    )
    deployed_summary = (
        b'    if path == BASE + "/summary":\n'
        b'        if method != "GET":\n'
        b'            raise ApiError(405, "METHOD_NOT_ALLOWED", "Method not supported for this endpoint.")\n'
        b"        with transaction() as db:\n"
        b'            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")\n'
        b"            return response(200, Repository(db, principal).summary(), correlation)\n"
        b'    if path != BASE and not path.startswith(BASE + "/"):\n'
        b'        raise ApiError(404, "ROUTE_NOT_FOUND", "Endpoint not found.")\n'
        b'    parts = path[len(BASE) :].strip("/").split("/") if path != BASE else []\n'
    )
    return replace_once(source, repository_summary, deployed_summary, "target summary route order")


def check_checkout(expected_branch):
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    require(branch == expected_branch, f"Check out the exact release source branch {expected_branch}")
    paths = [
        "scripts/deploy-eks-upgrade-plans-prod.py",
        "src/navigan/modules/cluster_management/handler.py",
        "src/navigan/modules/cluster_management/models.py",
        "src/navigan/modules/cluster_management/upgrade_readiness.py",
        "src/navigan/modules/cluster_management/upgrade_plans.py",
        "src/navigan/modules/cluster_management/utility_upgrades.py",
        "src/navigan/modules/cluster_management/utility_gitops.py",
        "src/navigan/modules/cluster_management/upgrade_paths.py",
        "src/navigan/modules/cluster_management/upgrade_actors.py",
        "infrastructure/modules/cluster-management/template.yaml",
    ]
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", *paths], cwd=ROOT, text=True)
    require(not dirty.strip(), "Commit the reviewed EKS upgrade-plan release sources first")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def utility_yaml_dependency(fetch=None):
    """Pinned official PyPI wheel for the existing CPython 3.12 Linux x86_64 Lambda."""
    if fetch:
        payload = fetch(UTILITY_YAML_URL)
    else:
        with urllib.request.urlopen(UTILITY_YAML_URL, timeout=20) as response:
            payload = response.read(2_000_001)
    require(len(payload) <= 2_000_000 and digest(payload) == UTILITY_YAML_SHA, "PyYAML artifact checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as wheel:
        names = wheel.namelist()
        require(len(names) == len(set(names)), "Duplicate dependency ZIP entries")
        require(sum(entry.file_size for entry in wheel.infolist()) <= 20_000_000, "PyYAML artifact exceeds size limit")
        require(all(name.startswith(("yaml/", "_yaml/", "PyYAML.libs/", "PyYAML-6.0.2.dist-info/")) and ".." not in name.split("/") and "\\" not in name for name in names), "Unexpected dependency artifact paths")
        require("yaml/__init__.py" in names and "yaml/_yaml.cpython-312-x86_64-linux-gnu.so" in names, "Wrong PyYAML runtime artifact")
        return {name: wheel.read(name) for name in names if not name.endswith("/")}


def package_utilities(original, destination, yaml_dependency=None):
    """Replace utility modules and fix the scoped query; preserve EKS behavior."""
    prefix = "navigan/modules/cluster_management/"
    replacements = {prefix + name: (ROOT / "src" / prefix / name).read_bytes()
                    for name in ("utility_upgrades.py", "utility_gitops.py")}
    def replaced_cache(name):
        return (
            str(Path(name).parent) in {prefix.rstrip("/"), prefix + "__pycache__"}
            and name.endswith(".pyc")
            and any(f"/{module}." in name for module in ("handler", "utility_upgrades", "utility_gitops"))
        )
    with zipfile.ZipFile(original) as old:
        names = old.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP members rejected")
        for module in ("handler", "upgrade_readiness", "upgrade_plans", "upgrade_paths", "upgrade_actors", "utility_upgrades", "github_app", "repository"):
            require(prefix + module + ".py" in names, "Utilities-only baseline dependency missing: " + module)
        handler = scoped_handler_target(git_source(DEPLOYED_PLAN_TREE, "src/" + prefix + "handler.py"))
        handlers = [handler, retry_response_handler(handler)]
        require(semantic(old.read(prefix + "handler.py")) in {
            semantic(version) for candidate in handlers for version in (candidate, utility_query_handler(candidate))
        }, "Unreviewed utility routing contract")
        replacements[prefix + "handler.py"] = utility_query_handler(old.read(prefix + "handler.py"))
        for module in ("upgrade_plans", "utility_upgrades"):
            reviewed_trees = (DEPLOYED_PLAN_TREE, DEPLOYED_UTILITY_TREE) if module == "utility_upgrades" else (DEPLOYED_PLAN_TREE,)
            require(normalized_semantic(old.read(prefix + module + ".py")) in {
                normalized_semantic(git_source(tree, "src/" + prefix + module + ".py")) for tree in reviewed_trees
            }, "Unreviewed utility dependency: " + module)
        for module, class_name, method in (("github_app", "GitHubApp", "repository_token"), ("github_app", "GitHubApp", "_request"), ("repository", "Repository", "system_repository_access")):
            tree = ast.parse(old.read(prefix + module + ".py"))
            require(any(isinstance(node, ast.ClassDef) and node.name == class_name and any(isinstance(child, ast.FunctionDef) and child.name == method for child in node.body) for node in tree.body), "Required utility dependency unavailable: " + method)
        dependencies = {} if "yaml/__init__.py" in names else yaml_dependency
        require(isinstance(dependencies, dict) and ("yaml/__init__.py" in names or "yaml/__init__.py" in dependencies), "Pinned PyYAML dependency is required")
        require(all(name.startswith(("yaml/", "_yaml/", "PyYAML.libs/", "PyYAML-6.0.2.dist-info/")) and ".." not in name.split("/") and "\\" not in name for name in dependencies), "Unexpected utility dependency paths")
        require(not set(dependencies).intersection(names), "Utility dependency would overwrite an existing file")
        preserved = {name: digest(old.read(name)) for name in names if name not in replacements and not replaced_cache(name)}
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as new:
            for entry in old.infolist():
                if entry.filename not in replacements and not replaced_cache(entry.filename):
                    new.writestr(entry, old.read(entry.filename))
            for name in sorted(replacements):
                new.writestr(name, replacements[name])
            for name, content in sorted(dependencies.items()):
                new.writestr(name, content)
    with zipfile.ZipFile(destination) as new:
        require(set(new.namelist()) == set(preserved) | set(replacements) | set(dependencies), "Unexpected utility package members")
        require(all(digest(new.read(name)) == sha for name, sha in preserved.items()), "Unrelated production module changed")
        require(sum(item.file_size for item in new.infolist()) <= 250 * 1024 * 1024, "Updated ClusterFunction package is too large")
    return destination


def package(original, destination, *, utilities_only=False, yaml_dependency=None):
    if utilities_only:
        return package_utilities(original, destination, yaml_dependency)
    prefix = "navigan/modules/cluster_management/"
    handler = prefix + "handler.py"
    readiness = prefix + "upgrade_readiness.py"
    new_module = prefix + "upgrade_plans.py"
    utility_module = prefix + "utility_upgrades.py"
    utility_gitops = prefix + "utility_gitops.py"
    paths_module = prefix + "upgrade_paths.py"
    actors_module = prefix + "upgrade_actors.py"
    with zipfile.ZipFile(original) as old:
        names = old.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP members rejected")
        require(handler in names and readiness in names, "Deployed ClusterFunction baseline is incomplete")
        reviewed_handler = git_source(
            BASELINE_TREE, "src/navigan/modules/cluster_management/handler.py"
        )
        plans_installed = new_module in names
        expected_handler = (
            scoped_handler_target(git_source(DEPLOYED_PLAN_TREE, "src/" + handler))
            if plans_installed else deployed_handler_baseline(reviewed_handler)
        )
        require(
            semantic(old.read(handler)) in {
                semantic(expected_handler),
                semantic(retry_response_handler(expected_handler)) if plans_installed else semantic(expected_handler),
            },
            "Deployed handler differs from the reviewed production baseline",
        )
        reviewed_readiness = git_source(
            DEPLOYED_PLAN_TREE if plans_installed else BASELINE_TREE,
            "src/navigan/modules/cluster_management/upgrade_readiness.py"
        )
        require(
            normalized_semantic(old.read(readiness)) == normalized_semantic(reviewed_readiness),
            "Deployed upgrade-readiness module differs from the reviewed production baseline",
        )
        if plans_installed:
            require(
                semantic(old.read(new_module)) == semantic(git_source(DEPLOYED_PLAN_TREE, "src/" + new_module)),
                "Deployed upgrade-plan module differs from the reviewed production baseline",
            )
        if paths_module in names:
            require(semantic(old.read(paths_module)) == semantic(git_source(DEPLOYED_PLAN_TREE, "src/" + paths_module)), "Deployed component-path module differs from reviewed release")
        if actors_module in names:
            require(semantic(old.read(actors_module)) == semantic(git_source(DEPLOYED_PLAN_TREE, "src/" + actors_module)), "Deployed actor-name module differs from reviewed release")
        if utility_module in names:
            require(semantic(old.read(utility_module)) == semantic(git_source(DEPLOYED_PLAN_TREE, "src/" + utility_module)), "Deployed utility plan module differs from reviewed release")
        target_handler = scoped_handler_target(
            (ROOT / "src/navigan/modules/cluster_management/handler.py").read_bytes()
        )
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as new:
            for entry in old.infolist():
                if entry.filename in {new_module, utility_module, utility_gitops, paths_module, readiness, actors_module}:
                    continue
                if entry.filename.endswith(".pyc") and any(
                    f"/{name}." in entry.filename
                    for name in ("handler", "upgrade_readiness", "upgrade_plans", "utility_upgrades", "utility_gitops", "upgrade_paths", "upgrade_actors")
                ):
                    continue
                new.writestr(entry, target_handler if entry.filename == handler else old.read(entry.filename))
            new.writestr(readiness, (ROOT / "src" / readiness).read_bytes())
            new.writestr(new_module, (ROOT / "src" / new_module).read_bytes())
            new.writestr(utility_module, (ROOT / "src" / utility_module).read_bytes())
            new.writestr(utility_gitops, (ROOT / "src" / utility_gitops).read_bytes())
            new.writestr(paths_module, (ROOT / "src" / paths_module).read_bytes())
            new.writestr(actors_module, (ROOT / "src" / actors_module).read_bytes())
    with zipfile.ZipFile(destination) as updated:
        require(
            sum(item.file_size for item in updated.infolist()) <= 250 * 1024 * 1024,
            "Updated ClusterFunction package is too large",
        )
    return destination


def verify_database(session, parent):
    params = {item["ParameterKey"]: item["ParameterValue"] for item in parent.get("Parameters", [])}
    require(params.get("DatabaseName") == "navigan", "Expected PROD database navigan")
    cluster = session.client("rds").describe_db_clusters(DBClusterIdentifier="aws-infra-platform-db")[
        "DBClusters"
    ][0]
    result = session.client("rds-data").execute_statement(
        resourceArn=cluster["DBClusterArn"],
        secretArn=params["ApiDatabaseSecretArn"],
        database="navigan",
        sql=(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='cluster_management' AND table_name='upgrade_plans' AND column_name='plan_spec') AS path_column, "
            "EXISTS(SELECT 1 FROM access_management.privileges WHERE privilege_code='cluster.upgrade.execute') AS execution_privilege, "
            "to_regclass('cluster_management.upgrade_plans')::text AS table_name, "
            "to_regclass('cluster_management.utility_upgrade_plans')::text AS utility_table, "
            "has_table_privilege('navigan_api','cluster_management.utility_upgrade_plans','SELECT,INSERT,UPDATE') AS utility_grants, "
            "EXISTS(SELECT 1 FROM access_management.privileges WHERE privilege_code='cluster.upgrade.plan') AS planning_privilege, "
            "has_table_privilege('navigan_api','cluster_management.upgrade_plans',"
            "'SELECT,INSERT,UPDATE') AS runtime_grants"
        ),
        formatRecordsAs="JSON",
    )
    rows = json.loads(result["formattedRecords"])
    require(
        len(rows) == 1 and rows[0].get("table_name") and rows[0].get("runtime_grants") is True
        and rows[0].get("path_column") is True and rows[0].get("execution_privilege") is True
        and rows[0].get("utility_table") and rows[0].get("utility_grants") is True and rows[0].get("planning_privilege") is True,
        "Apply confirmed scoped migrations 029–033 before preparing the backend release",
    )


def preflight(session):
    parent, root, record = base.preflight(session)
    verify_database(session, parent)
    gateway = session.client("apigatewayv2")
    existing = {
        item["RouteKey"]: item
        for item in support.all_items(gateway, "get_routes", "Items", ApiId=record["api"])
    }
    presence = {}
    for logical, route_key in ROUTES.items():
        route = existing.get(route_key)
        presence[logical] = bool(route)
        if route:
            reference = record["reference"]
            require(
                all(
                    route.get(key, [] if key == "AuthorizationScopes" else None)
                    == reference.get(key, [] if key == "AuthorizationScopes" else None)
                    for key in ("AuthorizationType", "AuthorizerId", "AuthorizationScopes", "Target")
                ),
                f"Existing route protection differs for {route_key}",
            )
    record["planRoutePresence"] = presence
    return parent, root, record


def validate_delta(before, after, function_logical, presence):
    require(before.keys() == after.keys(), "Nested template settings changed")
    require(
        all(before[key] == after[key] for key in before if key != "Resources"),
        "Nested template settings changed",
    )
    old, new = before["Resources"], after["Resources"]
    require(set(old) <= set(new), "Cluster resource deletion rejected")
    additions = {logical for logical in ROUTES if not presence[logical]}
    require(set(new) - set(old) == additions, "Unexpected Cluster resource addition")
    for key in old:
        if key == function_logical:
            expected = copy.deepcopy(old[key])
            expected["Properties"]["Code"] = new[key]["Properties"]["Code"]
            require(expected == new[key], "Only ClusterFunction code may change")
        else:
            require(old[key] == new[key], "Unrelated Cluster resource changed: " + key)


def proposed_child(record, code):
    after = copy.deepcopy(record["before"])
    function = record["functionLogical"]
    after["Resources"][function]["Properties"]["Code"] = code
    reference = record["reference"]
    for logical, route_key in ROUTES.items():
        if not record["planRoutePresence"][logical]:
            after["Resources"][logical] = {
                "Type": "AWS::ApiGatewayV2::Route",
                "Properties": {
                    "ApiId": record["api"],
                    "RouteKey": route_key,
                    "Target": reference["Target"],
                    "AuthorizationType": reference["AuthorizationType"],
                    "AuthorizerId": reference["AuthorizerId"],
                    "AuthorizationScopes": reference.get("AuthorizationScopes", []),
                },
            }
    validate_delta(record["before"], after, function, record["planRoutePresence"])
    return after


def inspect_change_set(cfn, identifier, saved):
    root = cfn.describe_change_set(ChangeSetName=identifier)
    require(
        root["StackName"] == PARENT
        and root["Status"] == "CREATE_COMPLETE"
        and root["ExecutionStatus"] == "AVAILABLE",
        "Prepared production change set is unavailable",
    )
    changes = support.all_items(cfn, "describe_change_set", "Changes", ChangeSetName=identifier)
    require(len(changes) == 1, "Only ClusterManagement may change")
    change = changes[0]["ResourceChange"]
    require(
        change["LogicalResourceId"] == "ClusterManagement"
        and change["ResourceType"] == "AWS::CloudFormation::Stack"
        and change["Action"] == "Modify"
        and change.get("Replacement", "False") == "False"
        and change.get("ChangeSetId"),
        "Unexpected production root change",
    )
    child_id = change["ChangeSetId"]
    child = cfn.describe_change_set(ChangeSetName=child_id)
    require(child["StackId"] == saved["stack"], "Wrong nested Cluster stack")
    before = support.body(
        cfn.get_template(StackName=saved["stack"], TemplateStage="Processed")["TemplateBody"]
    )
    after = support.body(
        cfn.get_template(StackName=saved["stack"], ChangeSetName=child_id, TemplateStage="Processed")[
            "TemplateBody"
        ]
    )
    require(
        digest(json.dumps(after, sort_keys=True).encode()) == saved["templateHash"],
        "Prepared template changed",
    )
    validate_delta(before, after, saved["functionLogical"], saved["planRoutePresence"])
    nested = support.all_items(cfn, "describe_change_set", "Changes", ChangeSetName=child_id)
    allowed = {saved["functionLogical"], saved["integrationLogical"]} | {
        logical for logical in ROUTES if not saved["planRoutePresence"][logical]
    }
    logical_ids = {item["ResourceChange"]["LogicalResourceId"] for item in nested}
    require(logical_ids <= allowed, "Unrelated nested change")
    require(saved["functionLogical"] in logical_ids, "ClusterFunction update missing")
    for item in nested:
        value = item["ResourceChange"]
        require(value.get("Replacement", "False") == "False", "Resource replacement rejected")
        logical = value["LogicalResourceId"]
        if logical == saved["functionLogical"]:
            require(
                value["Action"] == "Modify" and value["ResourceType"] == "AWS::Lambda::Function",
                "ClusterFunction must be modified in place",
            )
        elif logical == saved["integrationLogical"]:
            require(
                value["Action"] == "Modify"
                and value["ResourceType"] == "AWS::ApiGatewayV2::Integration"
                and before["Resources"][logical] == after["Resources"][logical]
                and support.references(before["Resources"][logical], saved["functionLogical"]),
                "Only the unchanged Cluster integration dependency may refresh",
            )
        else:
            require(
                logical in ROUTES
                and value["Action"] == "Add"
                and value["ResourceType"] == "AWS::ApiGatewayV2::Route",
                "Upgrade-plan routes must be protected additions",
            )


def signature(record):
    return {
        key: record[key]
        for key in (
            "stack",
            "stackStamp",
            "function",
            "functionLogical",
            "integrationLogical",
            "revision",
            "oldSha",
            "api",
            "planRoutePresence",
        )
    }


def prepare(session, revision, *, utilities_only=False):
    parent, root, record = preflight(session)
    workspace = support.storage.verify_storage(session, "artifact-workspace")
    directory = Path(tempfile.mkdtemp(prefix="navigan-prod-eks-plans-"))
    directory.chmod(0o700)
    print("Private rollback/release record: " + str(directory), flush=True)
    deployed = session.client("lambda").get_function(FunctionName=record["function"])
    require(
        deployed["Configuration"]["RevisionId"] == record["revision"],
        "ClusterFunction changed during preparation",
    )
    original = directory / "ClusterFunction-original.zip"
    with urllib.request.urlopen(deployed["Code"]["Location"], timeout=60) as stream:
        original.write_bytes(stream.read())
    require(
        code_hash(original.read_bytes()) == record["oldSha"], "Original ClusterFunction checksum mismatch"
    )
    if utilities_only:
        require(all(record["planRoutePresence"].values()), "Utilities-only release requires existing protected upgrade routes")
    yaml_dependency = None
    with zipfile.ZipFile(original) as captured:
        yaml_present = "yaml/__init__.py" in captured.namelist()
    require(utilities_only or yaml_present, "Use --utilities-only to add the pinned utility dependency without replacing EKS modules")
    if utilities_only and not yaml_present:
        require(deployed["Configuration"].get("Runtime") == "python3.12" and deployed["Configuration"].get("Architectures", ["x86_64"]) == ["x86_64"], "Pinned utility dependency requires the reviewed Python 3.12 x86_64 Lambda")
        yaml_dependency = utility_yaml_dependency()
    updated = package(original, directory / "ClusterFunction-updated.zip", utilities_only=utilities_only, yaml_dependency=yaml_dependency)
    code, _ = support.upload(session, workspace, directory, "eks-upgrade-plans.zip", updated.read_bytes())
    child = proposed_child(record, code)
    _, child_url = support.upload(
        session, workspace, directory, "eks-upgrade-plans-cluster-template.json", json.dumps(child).encode()
    )
    updated_root = copy.deepcopy(root)
    updated_root["Resources"]["ClusterManagement"]["Properties"]["TemplateURL"] = child_url
    _, root_url = support.upload(
        session,
        workspace,
        directory,
        "eks-upgrade-plans-parent-template.json",
        json.dumps(updated_root).encode(),
    )
    cfn = session.client("cloudformation")
    request = {
        "StackName": PARENT,
        "ChangeSetName": "navigan-prod-eks-plans-" + uuid.uuid4().hex[:16],
        "ChangeSetType": "UPDATE",
        "TemplateURL": root_url,
        "IncludeNestedStacks": True,
        "Capabilities": ["CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"],
        "Parameters": [
            {"ParameterKey": item["ParameterKey"], "UsePreviousValue": True}
            for item in parent.get("Parameters", [])
        ],
    }
    if parent.get("RoleARN"):
        request["RoleARN"] = parent["RoleARN"]
    identifier = cfn.create_change_set(**request)["Id"]
    cfn.get_waiter("change_set_create_complete").wait(
        ChangeSetName=identifier, WaiterConfig={"Delay": 5, "MaxAttempts": 180}
    )
    saved = {
        **signature(record),
        "templateHash": digest(json.dumps(child, sort_keys=True).encode()),
        "newSha": code_hash(updated.read_bytes()),
    }
    inspect_change_set(cfn, identifier, saved)
    plan = directory / "release-plan.json"
    dump(
        plan,
        {
            "format": FORMAT,
            "account": ACCOUNT,
            "region": REGION,
            "revision": revision,
            "releaseScope": "UTILITIES_ONLY" if utilities_only else "EKS_PLANS",
            "utilityDependencies": {"PyYAML": {"version": "6.0.2", "sha256": UTILITY_YAML_SHA}} if yaml_dependency else {},
            "parentStamp": base.stamp(parent),
            "changeSet": identifier,
            "release": saved,
        },
    )
    label = "Utilities-only PROD API release" if utilities_only else "Scoped PROD EKS plan API release"
    print(label + " prepared; NOT executed. Release plan: " + str(plan))


def execute(session, plan_path):
    plan = json.loads(plan_path.read_text())
    require(
        (plan.get("format"), plan.get("account"), plan.get("region")) == (FORMAT, ACCOUNT, REGION),
        "Wrong EKS upgrade-plan release plan",
    )
    parent, _, current = preflight(session)
    saved = plan["release"]
    require(plan.get("releaseScope", "EKS_PLANS") in {"EKS_PLANS", "UTILITIES_ONLY"}, "Unknown backend release scope")
    if plan.get("releaseScope") == "UTILITIES_ONLY":
        require(all(saved["planRoutePresence"].values()), "Utilities-only release cannot add routes")
    require(base.stamp(parent) == plan["parentStamp"], "Production parent stack changed; prepare again")
    require(
        signature(current) == {key: saved[key] for key in signature(current)},
        "Cluster API changed; prepare again",
    )
    cfn = session.client("cloudformation")
    inspect_change_set(cfn, plan["changeSet"], saved)
    cfn.execute_change_set(ChangeSetName=plan["changeSet"])
    print("Waiting for the scoped Cluster API deployment", flush=True)
    cfn.get_waiter("stack_update_complete").wait(
        StackName=PARENT, WaiterConfig={"Delay": 10, "MaxAttempts": 180}
    )
    _, _, deployed = preflight(session)
    require(deployed["oldSha"] == saved["newSha"], "Deployed ClusterFunction checksum differs")
    require(all(deployed["planRoutePresence"].values()), "Protected upgrade-plan routes were not deployed")
    if plan.get("releaseScope") == "UTILITIES_ONLY":
        print("PROD utility planning API deployed and verified. No utility upgrade was started.")
    else:
        print("PROD governed EKS upgrade-plan API deployed and verified. No EKS upgrade was started.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--source-branch", default="feature/eks-upgrade-readiness")
    parser.add_argument("--utilities-only", action="store_true", help="Preserve deployed EKS modules; replace only utility planning modules")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", type=Path, metavar="PLAN")
    args = parser.parse_args()
    revision = check_checkout(args.source_branch)
    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    require(session.client("sts").get_caller_identity()["Account"] == ACCOUNT, "Wrong AWS account")
    require(not (args.execute and args.utilities_only), "Execution uses the scope saved in the release plan; omit --utilities-only")
    execute(session, args.execute) if args.execute else prepare(session, revision, utilities_only=args.utilities_only)


if __name__ == "__main__":
    main()
