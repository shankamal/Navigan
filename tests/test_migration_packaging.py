from pathlib import Path


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


def test_rbac_is_read_only_and_excludes_sensitive_resources():
    rbac = read(CHART / "templates/rbac.yaml").lower()

    for forbidden_resource in (
        "secrets",
        "configmaps",
        "pods",
        "events",
        "roles",
        "rolebindings",
        "clusterroles",
        "clusterrolebindings",
    ):
        assert f"- {forbidden_resource}\n" not in rbac

    for forbidden_verb in (
        "create",
        "update",
        "patch",
        "delete",
        "watch",
        "bind",
        "escalate",
        "impersonate",
    ):
        assert f'"{forbidden_verb}"' not in rbac

    assert 'verbs: ["list"]' in rbac
    assert 'verbs: ["get"]' in rbac
    assert 'nonresourceurls: ["/version"]' in rbac


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
