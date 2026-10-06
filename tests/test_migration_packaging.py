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


def test_job_has_restricted_runtime_security():
    job = read(CHART / "templates/job.yaml")

    for required in (
        "kind: Job",
        "automountServiceAccountToken: false",
        "runAsNonRoot: true",
        "allowPrivilegeEscalation: false",
        "readOnlyRootFilesystem: true",
        "seccompProfile:",
        "drop:",
        "- ALL",
        "restartPolicy: Never",
        "activeDeadlineSeconds:",
        "sizeLimit: 16Mi",
    ):
        assert required in job

    assert "image.digest is required" in job
    assert "hostNetwork: true" not in job
    assert "privileged: true" not in job


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
    job = read(CHART / "templates/job.yaml")

    assert "automountServiceAccountToken: false" in service_account
    assert "serviceAccountToken:" in job
    assert "expirationSeconds: 3600" in job
