import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from migration_connector.deployment_evidence import collect_runtime
from migration_connector.inventory import sanitize_resource, finalize_inventory
from navigan.modules.migration_management.deployment_sources import (
    DeploymentSourcesConfig,
    analyze_repository,
    build_report,
    config_digest,
    image_parts,
    check_image,
)
from navigan.modules.migration_management.models import SourceInventoryReport
from navigan.modules.migration_management.service import Service
from navigan.modules.migration_management.handler import route_of
from navigan.shared.errors import ApiError

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
COMMIT = "c" * 40
IDENTITY = {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "shop", "name": "api"}


def deployment():
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "namespace": "shop",
            "name": "api",
            "labels": {
                "helm.sh/chart": "shop-1.2.0",
                "app.kubernetes.io/managed-by": "Helm",
                "app.kubernetes.io/version": "2.1",
                "private": "do-not-export",
            },
            "annotations": {
                "meta.helm.sh/release-name": "shop",
                "kubectl.kubernetes.io/last-applied-configuration": "do-not-export",
                "token": "do-not-export",
            },
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [{"name": "api", "image": "example/api:v2"}],
                    "initContainers": [{"name": "migrate", "image": "example/migrate:v2"}],
                }
            }
        },
    }


def owned(kind, name):
    return {"kind": kind, "name": name, "controller": True}


def runtime_request(path):
    if path.endswith("replicasets"):
        return {"items": [{"metadata": {"name": "api-rs", "ownerReferences": [owned("Deployment", "api")]}}]}
    if path.endswith("jobs"):
        return {"items": []}
    return {
        "items": [
            {
                "metadata": {"name": "api-pod", "ownerReferences": [owned("ReplicaSet", "api-rs")]},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": "api",
                            "image": "example/api:v2",
                            "imageID": "example/api@" + DIGEST,
                            "ready": True,
                        }
                    ],
                    "initContainerStatuses": [
                        {
                            "name": "migrate",
                            "image": "example/migrate:v2",
                            "imageID": "example/migrate@" + OTHER,
                            "ready": False,
                        }
                    ],
                },
            }
        ]
    }


def test_runtime_is_owner_linked_and_only_safe_metadata_leaves_cluster():
    resources = [sanitize_resource(deployment())]
    collect_runtime("shop", runtime_request, resources)
    item = resources[0]
    assert item["runtimeEvidence"]["status"] == "OBSERVED"
    assert len(item["runtimeEvidence"]["containers"]) == 2
    assert {v["containerType"] for v in item["runtimeEvidence"]["containers"]} == {"APPLICATION", "INIT"}
    assert "do-not-export" not in json.dumps(item)
    value = finalize_inventory(resources)
    SourceInventoryReport.model_validate(
        {
            **value,
            "migrationVersion": 5,
            "observedAt": "2026-10-19T10:00:00Z",
            "sourceKubernetesVersion": "v1.37.1",
        }
    )


def test_denied_pod_access_is_a_gap_and_never_fabricated_completion():
    resources = [sanitize_resource(deployment())]

    def denied(path):
        if path.endswith("pods"):
            raise RuntimeError("HTTP 403")
        return {"items": []}

    collect_runtime("shop", denied, resources)
    assert resources[0]["runtimeEvidence"] == {"status": "UNAVAILABLE", "containers": []}


def test_same_image_or_pod_name_does_not_imply_controller_ownership():
    resources = [sanitize_resource(deployment())]

    def unrelated(path):
        result = runtime_request(path)
        if path.endswith("pods"):
            result["items"][0]["metadata"]["ownerReferences"] = [owned("ReplicaSet", "other-rs")]
        return result

    collect_runtime("shop", unrelated, resources)
    assert resources[0]["runtimeEvidence"]["containers"] == []
    assert resources[0]["runtimeEvidence"]["status"] == "NO_RUNNING_EVIDENCE"


def test_finished_pods_are_not_reported_as_currently_running():
    resources = [sanitize_resource(deployment())]

    def finished(path):
        result = runtime_request(path)
        if path.endswith("pods"):
            result["items"][0]["status"]["phase"] = "Succeeded"
        return result

    collect_runtime("shop", finished, resources)
    assert resources[0]["runtimeEvidence"]["containers"] == []


def test_backend_rejects_unapproved_metadata_and_nested_runtime_fields():
    for malicious in (
        {"deploymentMetadata": {"labels": {"private": "secret"}}},
        {"runtimeEvidence": {"status": "OBSERVED", "containers": [], "rawPod": {}}},
    ):
        item = sanitize_resource(deployment())
        item.update(malicious)
        value = finalize_inventory([item])
        with pytest.raises(ValidationError):
            SourceInventoryReport.model_validate(
                {
                    **value,
                    "migrationVersion": 5,
                    "observedAt": "2026-10-19T10:00:00Z",
                    "sourceKubernetesVersion": "v1.37.1",
                }
            )


def test_repository_is_commit_pinned_and_script_bodies_are_never_saved():
    files = {
        "deploy/Chart.yaml": "apiVersion: v2\nname: shop\nversion: 1.2.0\n",
        "deploy/templates/api.yaml": "kind: Deployment\nmetadata:\n  name: {{ .Values.name }}\n",
        "deploy/deploy.sh": "SECRET=do-not-export\nhelm upgrade shop ./deploy -f values.yaml\n",
        "deploy/api.yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  namespace: shop\n  name: api\nspec:\n  template:\n    spec:\n      containers:\n      - name: api\n        image: example/api:v2\n",
    }
    calls = []

    def fetch(url, token=None):
        calls.append(url)
        if "/commits/" in url:
            return {"sha": COMMIT}
        if "/trees/" in url:
            return {
                "tree": [
                    {"type": "blob", "path": p, "sha": str(i), "size": len(content)}
                    for i, (p, content) in enumerate(files.items())
                ]
            }
        value = list(files.values())[int(url.rsplit("/", 1)[-1])]
        return {"content": base64.b64encode(value.encode()).decode()}

    result = analyze_repository(
        {"repository": "customer/shop", "revision": "production", "directory": "deploy"}, fetch=fetch
    )
    assert result["commit"] == COMMIT
    assert any(a["format"] == "HELM" for a in result["artifacts"])
    assert any(a.get("usesHelm") for a in result["artifacts"])
    assert any(a.get("resource") == IDENTITY for a in result["artifacts"])
    assert "do-not-export" not in json.dumps(result)
    assert "{{" not in json.dumps(result)
    assert any(COMMIT in c and "/trees/" in c for c in calls)


def test_yaml_aliases_are_reported_as_unresolved_not_expanded():
    def fetch(url, token=None):
        if "/commits/" in url:
            return {"sha": COMMIT}
        if "/trees/" in url:
            return {"tree": [{"type": "blob", "path": "deploy.yaml", "sha": "1"}]}
        return {"content": base64.b64encode(b"a: &a [1]\nb: *a\n").decode()}

    result = analyze_repository(
        {"repository": "customer/shop", "revision": "main", "directory": ""}, fetch=fetch
    )
    assert result["status"] == "PARTIAL"
    assert result["artifacts"] == []


def test_registry_is_explicitly_connected_and_account_bound():
    aws = MagicMock()
    img = "123456789012.dkr.ecr.ap-south-1.amazonaws.com/shop/api:2.0"
    host = img.split("/")[0]
    assert check_image(img, "123456789012", [], boto3_module=aws)["status"] == "NOT_CONNECTED"
    aws.client.return_value.describe_images.return_value = {"imageDetails": [{"imageDigest": DIGEST}]}
    result = check_image(img, "999999999999", [host], boto3_module=aws)
    assert result["registryDigest"] == DIGEST
    aws.client.return_value.describe_images.assert_called_once_with(
        registryId="123456789012", repositoryName="shop/api", imageIds=[{"imageTag": "2.0"}]
    )


def test_image_parsing_handles_ports_and_digest_pins():
    assert image_parts("registry.example.com:5000/team/api:1.2")["tag"] == "1.2"
    assert image_parts("nginx@" + DIGEST) == {
        "registry": "docker.io",
        "repository": "library/nginx",
        "tag": None,
        "digest": DIGEST,
    }


def test_candidate_is_not_verified_and_legacy_metadata_remains_unresolved():
    item = sanitize_resource(deployment())
    collect_runtime("shop", runtime_request, [item])
    config = {"repositories": [], "registries": []}
    artifact = {
        "repository": "customer/shop",
        "commit": COMMIT,
        "filePath": "deploy/Chart.yaml",
        "format": "HELM",
        "chartName": "shop",
        "chartVersion": "1.2.0",
    }
    source = {
        "source_cluster_id": "SRC-db",
        "delivery_configuration": {
            "deploymentDiscovery": config,
            "deploymentAnalysis": {
                "configurationDigest": config_digest(config),
                "repositories": [{"artifacts": [artifact]}],
            },
        },
    }
    inventory = {"inventoryDigest": "a" * 64, "resources": [item]}
    report = build_report({"migration_id": "MIG-db"}, inventory, source)
    row = report["workloads"][0]
    assert row["mappingStatus"] == "CANDIDATE"
    assert row["candidates"][0]["deployedCommitVerified"] is False
    assert row["containers"][0]["observedDigests"] == [DIGEST]
    config["confirmations"] = [{**IDENTITY, **{k: artifact[k] for k in ("repository", "commit", "filePath")}}]
    assert (
        build_report({"migration_id": "MIG-db"}, inventory, source)["workloads"][0]["mappingStatus"]
        == "CONFIRMED"
    )
    config["repositories"] = [{"repository": "other/repo"}]
    assert (
        build_report({"migration_id": "MIG-db"}, inventory, source)["workloads"][0]["mappingStatus"]
        == "UNRESOLVED"
    )
    legacy = {"source_cluster_id": "SRC-db"}
    item.pop("runtimeEvidence")
    item.pop("deploymentMetadata")
    row = build_report({"migration_id": "MIG-db"}, inventory, legacy)["workloads"][0]
    assert row["artifactFormat"] == "Unresolved"
    assert row["runtimeStatus"] == "NOT_COLLECTED"


@pytest.mark.parametrize(
    "bad", ["https://github.com/user:password@customer/repo", "owner/repo?token=x", "owner/repo/extra"]
)
def test_repository_credentials_and_non_repository_inputs_rejected(bad):
    with pytest.raises(ValidationError):
        DeploymentSourcesConfig.model_validate({"repositories": [{"repository": bad}]})


def test_directory_traversal_and_unscoped_registry_urls_rejected():
    with pytest.raises(ValidationError):
        DeploymentSourcesConfig.model_validate(
            {"repositories": [{"repository": "owner/repo", "directory": "../secrets"}]}
        )
    with pytest.raises(ValidationError):
        DeploymentSourcesConfig.model_validate({"registries": ["https://user:password@registry.example.com"]})


def service_context(monkeypatch):
    monkeypatch.setenv("MIGRATION_SOURCE_FIRST_ENABLED", "true")
    repo = MagicMock()
    repo.principal = SimpleNamespace(user_id="engineer")
    migration = {
        "migration_id": "MIG-db",
        "customer_id": "CUS-db",
        "version": 5,
        "created_by": "engineer",
        "status": "ASSESSMENT_READY",
        "source_configuration": {"sourceClusterId": "SRC-db"},
        "planning_draft": {"saved": "keep"},
    }
    source = {
        "source_cluster_id": "SRC-db",
        "customer_id": "CUS-db",
        "version": 2,
        "created_by": "engineer",
        "delivery_configuration": {},
    }
    repo.get.return_value = migration
    repo.get_source_cluster.return_value = source
    return Service(repo, MagicMock(), "corr"), repo, migration, source


def test_refresh_preserves_previous_evidence_and_requires_current_version(monkeypatch):
    service, repo, migration, source = service_context(monkeypatch)
    source["delivery_configuration"]["deploymentDiscovery"] = {"inventoryOnly": True}
    with pytest.raises(ApiError, match="Reload"):
        service.analyze_deployment_sources("MIG-db", {"version": 4, "refreshCluster": True})
    service.analyze_deployment_sources("MIG-db", {"version": 5, "refreshCluster": True})
    row, previous = repo.save.call_args.args[:2]
    assert row["status"] == "DISCOVERY_PENDING"
    assert row["planning_draft"] == {"saved": "keep"}
    assert migration["status"] == "ASSESSMENT_READY"
    repo.get_source_inventory.assert_not_called()
    service.access.require.assert_called_with("migration.edit")


def test_customer_boundary_and_dev_flag_are_enforced(monkeypatch):
    service, repo, migration, source = service_context(monkeypatch)
    source["customer_id"] = "CUS-other"
    with pytest.raises(ApiError) as error:
        service.deployment_evidence("MIG-db")
    assert error.value.code == "SOURCE_CUSTOMER_MISMATCH"
    monkeypatch.setenv("MIGRATION_SOURCE_FIRST_ENABLED", "false")
    with pytest.raises(ApiError) as error:
        service.deployment_evidence("MIG-db")
    assert error.value.status == 404


def test_confirmations_must_reference_inspected_artifacts(monkeypatch):
    service, repo, _, source = service_context(monkeypatch)
    config = {
        "repositories": [],
        "registries": [],
        "confirmations": [
            {**IDENTITY, "repository": "customer/shop", "commit": COMMIT, "filePath": "deploy.yaml"}
        ],
    }
    with pytest.raises(ApiError) as error:
        service.save_deployment_sources("SRC-db", {"version": 2, "configuration": config})
    assert error.value.code == "DEPLOYMENT_SOURCE_NOT_ANALYZED"
    repo.save_deployment_configuration.assert_not_called()


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "source-clusters/SRC-" + "a" * 32 + "/deployment-sources", "deployment_sources_get"),
        ("PUT", "source-clusters/SRC-" + "a" * 32 + "/deployment-sources", "deployment_sources_save"),
        ("GET", "migrations/MIG-" + "a" * 32 + "/deployment-evidence", "deployment_evidence_get"),
        ("POST", "migrations/MIG-" + "a" * 32 + "/deployment-evidence", "deployment_evidence_run"),
    ],
)
def test_api_routes(method, path, expected):
    assert route_of(method, "/api/v1/" + path)[0] == expected


def test_github_expressions_are_workflows_not_helm_templates():
    files = {
        ".github/workflows/images.yml": "name: Build\nrun: echo ${{ github.sha }}\n",
        "deploy/plain.yaml": "name: {{ custom.variable }}\n",
        "charts/shop/Chart.yaml": "apiVersion: v2\nname: shop\nversion: 1\n",
        "charts/shop/templates/api.yaml": "name: {{ .Values.name }}\n",
    }

    def fetch(url, token=None):
        if "/commits/" in url:
            return {"sha": COMMIT}
        if "/trees/" in url:
            return {"tree": [{"type": "blob", "path": path, "sha": str(i)} for i, path in enumerate(files)]}
        return {"content": base64.b64encode(list(files.values())[int(url.rsplit('/', 1)[-1])].encode()).decode()}

    report = analyze_repository({"repository": "org/shop", "revision": "main"}, fetch=fetch)
    formats = {a["filePath"]: a["format"] for a in report["artifacts"]}
    assert formats[".github/workflows/images.yml"] == "GITHUB_ACTIONS"
    assert formats["deploy/plain.yaml"] == "TEMPLATE"
    assert formats["charts/shop/templates/api.yaml"] == "HELM_TEMPLATE"


@pytest.mark.parametrize("manifest_namespace,kind,expected", [
    (None, "Deployment", "NAMESPACE_UNSPECIFIED"),
    ("shop", "Deployment", "RESOURCE_IDENTITY"),
    ("another", "Deployment", None),
    (None, "StatefulSet", None),
])
def test_namespace_omitted_manifests_remain_candidates_not_verified(manifest_namespace, kind, expected):
    item = sanitize_resource(deployment())
    item.pop("deploymentMetadata")
    artifact = {"repository": "customer/shop", "commit": COMMIT, "filePath": "api.yaml", "format": "MANIFESTS", "resource": {**IDENTITY, "kind": kind, "namespace": manifest_namespace}}
    config = {"repositories": [], "registries": []}
    source = {"source_cluster_id": "SRC-db", "delivery_configuration": {"deploymentDiscovery": config, "deploymentAnalysis": {"configurationDigest": config_digest(config), "repositories": [{"artifacts": [artifact]}]}}}
    row = build_report({"migration_id": "MIG-db"}, {"resources": [item]}, source)["workloads"][0]
    if expected:
        assert row["mappingStatus"] == "CANDIDATE"
        assert row["candidates"][0]["match"] == expected
        assert row["candidates"][0]["deployedCommitVerified"] is False
        assert row["artifactFormat"] == "Kubernetes manifests (candidate)"
        if expected == "NAMESPACE_UNSPECIFIED":
            assert any("namespace mapping needs confirmation" in gap for gap in row["gaps"])
    else:
        assert row["mappingStatus"] == "UNRESOLVED"
        assert not row["candidates"]


def test_field_manager_evidence_is_allowlisted_and_does_not_export_managed_fields():
    raw = deployment()
    raw["metadata"]["managedFields"] = [{"manager": "kubectl-client-side-apply", "fieldsV1": {"secret": "do-not-export"}}, {"manager": "private-manager-do-not-export"}]
    item = sanitize_resource(raw)
    item["deploymentMetadata"]["labels"] = {}
    item["deploymentMetadata"]["annotations"] = {}
    assert item["deploymentMetadata"]["fieldManagers"] == ["kubectl-client-side-apply"]
    assert "do-not-export" not in json.dumps(item)
    report = build_report({"migration_id": "MIG-db"}, {"inventoryDigest": "a" * 64, "resources": [item]}, {"source_cluster_id": "SRC-db"})
    row = report["workloads"][0]
    assert row["deliveryEvidenceBasis"] == "FIELD_MANAGER"
    assert row["deliveryTool"] == "kubectl (field-manager evidence)"
    assert row["clusterSnapshot"]["deployable"] is False
    assert row["clusterSnapshot"]["resourceIdentity"]["kind"] == "Deployment"
    assert report["coverage"]["workloadCount"] == 1
    assert report["coverage"]["status"] == "WITH_GAPS"


@pytest.mark.parametrize("kind", ["Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"])
def test_every_supported_workload_receives_snapshot_and_actionable_gaps(kind):
    item = sanitize_resource(deployment())
    item["kind"] = kind
    item["runtimeEvidence"] = {"status": "OBSERVED", "containers": [{"name": "api", "containerType": "APPLICATION", "podName": "api-pod", "image": "example/api:v2", "imageID": None, "ready": True}]}
    report = build_report({"migration_id": "MIG-db"}, {"resources": [item]}, {"source_cluster_id": "SRC-db"})
    row = report["workloads"][0]
    assert row["clusterSnapshot"]["resourceIdentity"]["kind"] == kind
    assert row["evidenceStatus"] == "REVIEW_REQUIRED"
    assert any("Running image digest was not reported" in gap for gap in row["gaps"])
    assert any("Registry verification is incomplete" in gap for gap in row["gaps"])
    assert row["registryVerified"] is False


def test_unconfigured_public_registries_are_checked_anonymously_but_private_ecr_requires_role(monkeypatch):
    import navigan.modules.migration_management.source_authentication as auth
    service, repo, _, _ = service_context(monkeypatch)
    item = sanitize_resource(deployment())
    item["pod"]["containers"] = [{"name": "api", "image": "quay.io/customer/api:v1"}, {"name": "private", "image": "123456789012.dkr.ecr.ap-south-1.amazonaws.com/app:v1"}]
    item["pod"]["initContainers"] = []
    repo.get_source_inventory.return_value = {"inventory": {"resources": [item]}}
    calls = []
    def public_read(host, credential, path, repository):
        calls.append((host, credential, path, repository))
        return {"_registryDigest": DIGEST}
    monkeypatch.setattr(auth, "registry_read", public_read)
    service.analyze_deployment_sources("MIG-db", {"version": 5})
    assert len(calls) == 1
    assert calls[0][0] == "quay.io" and calls[0][1] == {"mode": "PUBLIC"}
    analysis = repo.save_deployment_configuration.call_args.args[2]
    assert {item["status"] for item in analysis["images"]} == {"AVAILABLE", "NOT_CONNECTED"}


def test_untrusted_field_managers_are_rejected_by_inventory_validation():
    item = sanitize_resource(deployment())
    item["deploymentMetadata"]["fieldManagers"] = ["unapproved-manager"]
    value = finalize_inventory([item])
    with pytest.raises(ValidationError, match="field manager"):
        SourceInventoryReport.model_validate({**value, "migrationVersion": 5, "observedAt": "2026-10-19T10:00:00Z", "sourceKubernetesVersion": "v1.37.1"})


def test_continuation_reuses_completed_checks_only_for_matching_inventory_and_auth(monkeypatch):
    import navigan.modules.migration_management.source_authentication as auth
    service, repo, _, source = service_context(monkeypatch)
    item = sanitize_resource(deployment())
    item["pod"]["containers"] = [{"name": "a", "image": "quay.io/shop/a:1"}, {"name": "b", "image": "quay.io/shop/b:1"}]
    item["pod"]["initContainers"] = []
    repo.get_source_inventory.return_value = {"inventory": {"inventoryDigest": "a" * 64, "resources": [item]}}
    calls = []
    monkeypatch.setattr(auth, "registry_read", lambda host, credential, path, repository: calls.append(path) or {"_registryDigest": DIGEST})
    def save(current, key, value, correlation):
        current["delivery_configuration"][key] = value
    repo.save_deployment_configuration.side_effect = save
    service.analyze_deployment_sources("MIG-db", {"version": 5})
    assert len(calls) == 2
    source["delivery_configuration"]["deploymentAnalysis"]["images"][1]["status"] = "PENDING"
    calls.clear()
    service.analyze_deployment_sources("MIG-db", {"version": 5, "continueAnalysis": True})
    assert len(calls) == 1 and "/shop/b/" in calls[0]
    source["delivery_configuration"]["deploymentAuthentication"] = {"github:shop/app": {"secretVersion": "rotated"}}
    calls.clear()
    service.analyze_deployment_sources("MIG-db", {"version": 5, "continueAnalysis": True})
    assert len(calls) == 2  # Rotating access invalidates continuation state.
