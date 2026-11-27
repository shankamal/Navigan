import pytest
from navigan.modules.migration_management.network_evidence import network_scope_evidence
from navigan.modules.migration_management.resource_compatibility import evaluate_selected_resources


def svc(name, ns="retailflow"):
    return {"apiVersion": "v1", "kind": "Service", "namespace": ns, "name": name}


def ref(name):
    return {"kind": "Service", "name": name}


def workload(kind="Deployment", **extra):
    return {"apiVersion": "networking.k8s.io/v1" if kind == "Ingress" else "apps/v1",
            "kind": kind, "namespace": "retailflow", "name": "app", **extra}


def plan(*resources):
    return [{**r, "treatment": "MIGRATE"} for r in resources]


@pytest.mark.parametrize("kind,field", [("Deployment", "dependencyReferences"), ("Ingress", "backendServiceReferences"), ("CronJob", "dependencyReferences")])
def test_observed_selected_reference_is_only_partial(kind, field):
    source = workload(kind, **{field: [ref("api")]})
    target = svc("api")
    result = network_scope_evidence(source, plan(source, target), [source, target])
    assert result["status"] == "PARTIAL"
    assert "Selected source Services (1): api" in result["reason"]
    assert "remain unverified" in result["reason"]


def test_missing_and_omitted_are_distinct():
    source = workload(dependencyReferences=[ref("absent"), ref("not-selected"), ref("selected")])
    selected, omitted = svc("selected"), svc("not-selected")
    result = network_scope_evidence(source, plan(source, selected), [source, selected, omitted])
    assert result["status"] == "PENDING_EVIDENCE"
    assert "not observed in source inventory (1): absent" in result["reason"]
    assert "not marked MIGRATE (1): not-selected" in result["reason"]
    assert "Selected source Services (1): selected" in result["reason"]


def test_cross_namespace_name_does_not_satisfy_reference():
    source = workload(dependencyReferences=[ref("api")])
    other = svc("api", "other")
    result = network_scope_evidence(source, plan(source, other), [source, other])
    assert result["status"] == "PENDING_EVIDENCE"
    assert "not observed in source inventory" in result["reason"]


def test_retired_service_does_not_satisfy_scope():
    source, service = workload(dependencyReferences=[ref("api")]), svc("api")
    result = network_scope_evidence(source, plan(source) + [{**service, "treatment": "RETIRE"}], [source, service])
    assert result["status"] == "PENDING_EVIDENCE"
    assert "not marked MIGRATE" in result["reason"]


@pytest.mark.parametrize("refs", [None, [], {}, [None], [{"kind":"Service"}], [{"kind":"Secret","name":"key"}]])
def test_missing_empty_and_non_service_refs_never_certify_network(refs):
    source = workload(dependencyReferences=refs)
    assert network_scope_evidence(source, plan(source), [source])["status"] == "PENDING_EVIDENCE"


def test_non_network_resource_no_scope_check():
    assert network_scope_evidence({"kind": "ConfigMap"}, [], []) is None


def test_resource_report_retains_target_network_and_freshness_gates():
    source, service = workload(dependencyReferences=[ref("api")]), svc("api")
    report = evaluate_selected_resources([source, service], plan(source, service), [], [], [], [], target_current=False)
    checks = {c["capability"]: c for c in report[0]["checks"]}
    assert checks["Network dependency scope"]["status"] == "PARTIAL"
    assert checks["Workload networking dependencies"]["status"] == "PENDING_EVIDENCE"
    assert checks["Evidence freshness"]["status"] == "PENDING_EVIDENCE"
    assert report[0]["status"] == "PENDING_EVIDENCE"


def test_ingress_scope_does_not_imply_target_routing():
    source, service = workload("Ingress", backendServiceReferences=[ref("api")]), svc("api")
    report = evaluate_selected_resources([source, service], plan(source, service), [], [], [], [], target_current=True)
    checks = {c["capability"]: c for c in report[0]["checks"]}
    assert checks["Network dependency scope"]["status"] == "PARTIAL"
    assert checks["Networking"]["status"] == "PENDING_EVIDENCE"
    assert report[0]["status"] == "PENDING_EVIDENCE"
