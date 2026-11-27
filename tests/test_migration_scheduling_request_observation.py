import pytest

from navigan.modules.migration_management.scheduling_evidence import (
    regular_container_requests, workload_pod_requests,
)


def workload(**placement):
    return {"pod": {"containers": [
        {"resources": {"requests": {"cpu": "250m", "memory": "256Mi"}}},
        {"resources": {"requests": {"cpu": "500m", "memory": "512Mi"}}},
    ], **placement}}


@pytest.mark.parametrize("placement", [
    {"affinity": {"podAntiAffinity": True}},
    {"tolerations": [{"key": "system"}]},
    {"nodeSelectorKeys": ["zone"]},
    {"nodeSelector": {"zone": "a"}},
    {"initContainers": [{"resources": {"requests": {"cpu": "2", "memory": "2Gi"}}}]},
])
def test_requests_are_observed_without_claiming_effective_pod_demand(placement):
    resource = workload(**placement)
    assert regular_container_requests(resource) == {"cpu": "750m", "memory": str(768 * 1024**2)}
    assert workload_pod_requests(resource) is None


def test_simple_workload_remains_backward_compatible():
    assert regular_container_requests(workload()) == workload_pod_requests(workload())


@pytest.mark.parametrize("resource", [
    None, {}, {"pod": {}}, {"pod": {"containers": []}},
    {"pod": {"containers": [None]}},
    {"pod": {"containers": [{"resources": {"requests": {"cpu": "500m"}}}]}},
    {"pod": {"containers": [{"resources": {"requests": {"cpu": "bad", "memory": "1Gi"}}}]}},
])
def test_missing_requests_not_invented(resource):
    assert regular_container_requests(resource) is None
