from navigan.modules.cluster_management.system_repository import (
    render_system_repository,
)


def test_system_repository_renders_gitops_baseline_without_secrets():
    rendered = render_system_repository(
        repository_url="https://github.com/customer/cluster-system",
        connector_id="KCC-0123456789abcdef0123456789abcdef",
        cluster_id="CLU-ab5d1625584e4c7197112c7c590698ae",
        connector_image=(
            "123456789012.dkr.ecr.ap-south-1.amazonaws.com/"
            "navigan-cluster-connector@sha256:" + "a" * 64
        ),
        api_base_url="https://api.example.test/api/v1",
        tools_base_url="https://dev.navigan.click/tools",
    )

    assert "applications/05-connector.yaml" in rendered
    assert "applications/10-monitoring.yaml" in rendered
    assert "applications/20-falco.yaml" in rendered
    assert "applications/30-headlamp.yaml" in rendered
    assert "applications/31-headlamp-readonly.yaml" in rendered
    assert "charts/navigan-cluster-connector/templates/deployment.yaml" in rendered
    connector_rbac = rendered[
        "charts/navigan-cluster-connector/templates/rbac.yaml"
    ]
    assert 'resources: ["roles", "clusterroles"]' in connector_rbac
    assert 'verbs: ["bind", "escalate"]' in connector_rbac
    combined = "\n".join(rendered.values())
    assert "__" not in combined
    assert "connector-token" not in combined
    assert "githubToken" not in combined
    assert "navigan.io/platform-services" in combined
    assert "/var/run/navigan/ready" in combined
    assert "wss://dev.navigan.click/tools/tunnel" in combined
    assert "navigan-headlamp-readonly" in combined
    assert "- -proxy-auth=true" in combined
    assert "unsafeUseServiceAccountToken: true" in combined
    assert "name: navigan-dashboard" in rendered["values/headlamp.yaml"]
    assert "disable_login_form: true" in combined
    assert (
        "https://dev.navigan.click/tools/clusters/"
        "CLU-ab5d1625584e4c7197112c7c590698ae/grafana/"
    ) in combined
    monitoring_values = rendered["values/monitoring.yaml"]
    assert "admissionWebhooks:" in monitoring_values
    assert "patch:" in monitoring_values
    assert "navigan.io/system-only" in monitoring_values
    assert (
        "http://navigan-monitoring-prometheus.navigan-monitoring."
        "svc.cluster.local:9090/tools/clusters/"
        "CLU-ab5d1625584e4c7197112c7c590698ae/prometheus"
    ) in monitoring_values
    assert 'GF_AUTH_ANONYMOUS_ENABLED: "true"' in monitoring_values
    assert "path: /metrics" in monitoring_values
    assert "serve_from_sub_path: false" in monitoring_values
    assert "alertmanager:\n        enabled: false" in monitoring_values
    assert "initialDelaySeconds: 30" in monitoring_values
    headlamp_values = rendered["values/headlamp.yaml"]
    assert headlamp_values.count("initialDelaySeconds: 30") == 2
    assert headlamp_values.count("failureThreshold: 6") == 2
    project = rendered["applications/00-project.yaml"]
    assert "namespace: argocd" in project
    assert "namespace: kube-system" in project


def test_generated_falco_baseline_pins_verified_kernel_compatible_artifacts():
    import yaml
    from pathlib import Path

    rendered = render_system_repository(
        repository_url="https://github.com/customer/new-system",
        connector_id="KCC-test", cluster_id="CLU-test",
        connector_image="registry.example/connector@sha256:" + "a" * 64,
        api_base_url="https://api.example.test/api/v1",
    )
    roots = [rendered, {
        path: (Path(__file__).parents[1] / "platform/system-repo-template" / path).read_text()
        for path in ("applications/20-falco.yaml", "values/falco.yaml")
    }]
    for baseline in roots:
        application = yaml.safe_load(baseline["applications/20-falco.yaml"])
        values = yaml.safe_load(baseline["values/falco.yaml"])
        assert application["spec"]["sources"][0]["targetRevision"] == "9.2.0"
        assert values["image"]["tag"] == "0.45.1"
        assert values["collectors"]["containerEngine"]["pluginRef"].endswith("/container:0.7.5")
        assert values["driver"]["kind"] == "modern_ebpf"
        assert values["nodeSelector"]["navigan.io/platform-services"] == "true"
        assert {"key": "navigan.io/system-only", "operator": "Equal",
                "value": "true", "effect": "NoSchedule"} in values["tolerations"]

