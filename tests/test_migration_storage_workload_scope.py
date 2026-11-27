"""Workload-only storage checks must not imply data migration or provisioning success."""
import pytest
from navigan.modules.migration_management.storage_evidence import compare_storage_claims

PVC = {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "namespace": "apps",
       "name": "db", "storageClassName": "local", "requestedStorage": "10Gi",
       "accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem"}
SELECTED = {("v1", "PersistentVolumeClaim", "apps", "db")}
BASE = dict(fresh=True, class_details=[{"name": "gp3", "provisioner": "ebs.csi.aws.com",
                                       "volumeBindingMode": "WaitForFirstConsumer"}],
            csi_drivers=["ebs.csi.aws.com"],
            mappings=[{"namespace": "apps", "sourceClaim": "db", "targetStorageClass": "gp3"}])


def evaluate(strategy=None, **changes):
    return compare_storage_claims([PVC], SELECTED, ["gp3"], data_strategy=strategy,
                                  **{**BASE, **changes})[0]


def test_workload_only_requires_provisioning_not_data_transfer():
    row = evaluate("DATA_MIGRATION_HANDLED_SEPARATELY")
    assert row["status"] == "PARTIAL"
    assert "provisioning and mounting remain unverified" in row["reason"]
    assert "Persistent data migration is handled separately" in row["reason"]
    assert "snapshots" not in row["reason"]
    assert row["targetStorageClass"] == "gp3"


@pytest.mark.parametrize("strategy", [None, "UNDECIDED", "BACKUP_RESTORE", "REPLICATION", "NO_PERSISTENT_DATA"])
def test_legacy_strategies_preserve_existing_checks(strategy):
    row = evaluate(strategy)
    assert row["status"] == "PARTIAL"
    assert "snapshots and data movement remain unverified" in row["reason"]


@pytest.mark.parametrize("changes", [{"fresh": False}, {"csi_drivers": []},
                                      {"class_details": []}, {"mappings": []}])
def test_separate_data_does_not_bypass_storage_requirements(changes):
    row = evaluate("DATA_MIGRATION_HANDLED_SEPARATELY", **changes)
    assert row["status"] == "PENDING_EVIDENCE"


from navigan.modules.migration_management.resource_compatibility import evaluate_selected_resources


def workload_checks(types, strategy="DATA_MIGRATION_HANDLED_SEPARATELY", kind="Deployment"):
    workload = {"apiVersion": "apps/v1", "kind": kind, "namespace": "apps", "name": "web",
                "pod": {"serviceAccountName": "default", "imagePullSecretCount": 0,
                        "volumes": [{"name": f"v{i}", "type": t} for i, t in enumerate(types)]}}
    row = evaluate_selected_resources([workload], [{**workload, "treatment": "MIGRATE"}],
                                      [], [], [], [], target_current=True, data_strategy=strategy)[0]
    assert row["status"] == "PENDING_EVIDENCE"
    return {c["capability"]: c for c in row["checks"]}


@pytest.mark.parametrize("types", [["emptyDir"], ["downwardAPI"], ["emptyDir", "downwardAPI"]])
def test_ephemeral_builtin_volumes_do_not_require_csi(types):
    checks = workload_checks(types)
    assert "Workload volume dependencies" not in checks
    assert "Kubernetes API" in checks


@pytest.mark.parametrize("types", [["configMap"], ["secret"], ["projected"], ["emptyDir", "configMap"]])
def test_configuration_volumes_still_require_reference_validation(types):
    checks = workload_checks(types)
    assert "Workload volume dependencies" not in checks
    assert checks["Workload configuration volumes"]["status"] == "PENDING_EVIDENCE"


@pytest.mark.parametrize("type_", ["persistentVolumeClaim", "hostPath", "csi", "nfs", "ephemeral", "other", None])
def test_other_volume_types_still_require_storage_checks(type_):
    checks = workload_checks([type_])
    assert checks["Workload volume dependencies"]["status"] == "PENDING_EVIDENCE"
    assert "data migration" not in checks["Workload volume dependencies"]["nextAction"]


def test_mixed_volumes_require_both_checks():
    checks = workload_checks(["configMap", "persistentVolumeClaim"])
    assert "Workload volume dependencies" in checks
    assert "Workload configuration volumes" in checks


def test_stateful_storage_templates_remain_pending():
    checks = workload_checks(["emptyDir"], kind="StatefulSet")
    assert checks["Stateful storage dependencies"]["status"] == "PENDING_EVIDENCE"
    assert "mounting" in checks["Stateful storage dependencies"]["nextAction"]
