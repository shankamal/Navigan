from navigan.modules.migration_management.storage_evidence import compare_storage_claims
from navigan.modules.migration_management.scheduling_evidence import (
    scheduling_constraints, workload_pod_requests, cpu_millicores, memory_bytes,
)


def test_explicit_target_storage_mapping_used_instead_of_source_class():
    source = [{"apiVersion": "v1", "kind": "PersistentVolumeClaim", "namespace": "apps",
               "name": "data", "storageClassName": "legacy", "accessModes": ["ReadWriteOnce"],
               "requestedStorage": "1.5Gi", "volumeMode": "Filesystem"}]
    selected = {("v1", "PersistentVolumeClaim", "apps", "data")}
    result = compare_storage_claims(
        source, selected, ["gp3"], fresh=True,
        class_details=[{"name": "gp3", "provisioner": "ebs.csi.aws.com",
                        "volumeBindingMode": "WaitForFirstConsumer"}],
        csi_drivers=["ebs.csi.aws.com"],
        mappings=[{"namespace": "apps", "sourceClaim": "data", "targetStorageClass": "gp3"}],
    )
    assert len(result) == 1
    assert result[0]["sourceStorageClass"] == "legacy"
    assert result[0]["targetStorageClass"] == "gp3"
    assert result[0]["status"] == "PARTIAL"


def test_scheduling_constraints_never_become_verified_capacity():
    resource = {"pod": {"nodeSelectorKeys": ["nodepool"], "tolerations": [{"key": "dedicated"}],
                        "containers": [{"resources": {"requests": {"cpu": "500m", "memory": "1Gi"}}}]}}
    assert workload_pod_requests(resource) is None
    findings = scheduling_constraints(resource)
    assert any("selectors" in finding for finding in findings)
    assert any("Tolerations" in finding for finding in findings)


def test_decimal_quantities_are_parsed():
    assert cpu_millicores("0.5") == 500
    assert memory_bytes("1.5Gi") == 1610612736
