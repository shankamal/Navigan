from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "migration_connector"
CHART = PACKAGE / "helm"


def read(path):
    return path.read_text(encoding="utf-8")


def test_container_runs_as_non_root_without_package_manager():
    dockerfile = read(PACKAGE / "Dockerfile")

    assert "USER 10001:10001" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "migration_connector.agent"]' in dockerfile
    assert "pip uninstall --yes pip setuptools wheel" in dockerfile
    assert "COPY --chown=10001:10001" in dockerfile


def test_chart_does_not_create_or_accept_plaintext_credentials():
    templates = "\n".join(
        read(path)
        for path in (CHART / "templates").glob("*.yaml")
    )
    values = read(CHART / "values.yaml")

    assert "kind: Secret" not in templates
    assert "connectorToken:" not in values
    assert "secretKeyRef:" in templates
    assert "credentialsSecretName:" in values


def test_persistent_deployment_has_restricted_runtime_security():
    deployment = read(CHART / "templates/deployment.yaml")

    for required in (
        "kind: Deployment",
        "replicas: 1",
        "type: Recreate",
        "automountServiceAccountToken: false",
        "runAsNonRoot: true",
        "allowPrivilegeEscalation: false",
        "readOnlyRootFilesystem: true",
        "seccompProfile:",
        "drop:",
        "- ALL",
        "restartPolicy: Always",
        "NAVIGAN_SOURCE_CONNECTOR_ID",
        "NAVIGAN_SOURCE_CONNECTOR_TOKEN",
        "NAVIGAN_POLL_SECONDS",
        "sizeLimit: 16Mi",
    ):
        assert required in deployment

    assert "image.digest is required" in deployment
    assert "hostNetwork: true" not in deployment
    assert "privileged: true" not in deployment


def test_rbac_is_read_only_and_limits_assessment_resources():
    rendered = read(CHART / "templates/rbac.yaml").replace(
        "{{ .Release.Name }}", "test-connector"
    ).replace("{{ .Release.Namespace }}", "test-namespace")
    role, binding = list(yaml.safe_load_all(rendered))
    assert role["kind"] == "ClusterRole"
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    expected = {
        "": {"nodes", "namespaces", "services", "persistentvolumeclaims",
             "serviceaccounts", "configmaps", "secrets"},
        "apps": {"deployments", "statefulsets", "daemonsets"},
        "batch": {"jobs", "cronjobs"},
        "networking.k8s.io": {"ingresses", "networkpolicies"},
        "autoscaling": {"horizontalpodautoscalers"},
        "policy": {"poddisruptionbudgets"},
        "rbac.authorization.k8s.io": {
            "roles", "rolebindings", "clusterroles", "clusterrolebindings"},
        "admissionregistration.k8s.io": {
            "mutatingwebhookconfigurations", "validatingwebhookconfigurations"},
        "storage.k8s.io": {"storageclasses"},
        "apiextensions.k8s.io": {"customresourcedefinitions"},
    }
    observed = {}
    version_rules = []
    for rule in role["rules"]:
        if "nonResourceURLs" in rule:
            version_rules.append(rule)
            continue
        assert rule["verbs"] == ["list"]
        assert len(rule["apiGroups"]) == 1
        group = rule["apiGroups"][0]
        assert group not in observed
        observed[group] = set(rule["resources"])
    assert observed == expected
    assert version_rules == [{"nonResourceURLs": ["/version"], "verbs": ["get"]}]
    # Secret/ConfigMap list permission is existing read access, not metadata-only
    # RBAC. Agent/inventory tests verify values are excluded from reports.


def test_kubernetes_object_names_are_release_scoped():
    templates = "\n".join(
        read(path)
        for path in (CHART / "templates").glob("*.yaml")
    )

    assert templates.count("{{ .Release.Name }}") >= 6


def test_service_account_uses_explicit_projected_token():
    service_account = read(
        CHART / "templates/serviceaccount.yaml"
    )
    deployment = read(CHART / "templates/deployment.yaml")

    assert "automountServiceAccountToken: false" in service_account
    assert "serviceAccountToken:" in deployment
    assert "expirationSeconds: 3600" in deployment


def test_bootstrap_keeps_kubeconfig_local_and_secret_out_of_process_args():
    bootstrap = read(PACKAGE / "bootstrap.ps1")

    assert "Get-Content -LiteralPath $resolvedBootstrap" in bootstrap
    assert "/source-connectors/enroll" in bootstrap
    assert "kubectl @kubectlArgs apply -f -" in bootstrap
    assert "connector-token=$" not in bootstrap
    assert "--kubeconfig" not in bootstrap.lower()
    assert "Get-Content -LiteralPath $Kube" not in bootstrap
    assert "Clear-Content -LiteralPath $resolvedBootstrap" in bootstrap
    assert "Remove-Item -LiteralPath $resolvedBootstrap" in bootstrap
