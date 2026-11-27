
import pytest

from navigan.modules.migration_management.scheduling_evidence import (
    evaluate_combined_placement,
    observed_pod_request_floor,
    evaluate_node_tolerations,
)


def container(cpu="500m", memory="512Mi"):
    return {"resources": {"requests": {
        "cpu": cpu, "memory": memory
    }}}


def workload(**overrides):
    return {"pod": {
        "containers": [container()],
        "initContainers": [],
        "nodeSelector": {"zone": "a"},
        "tolerations": [],
        **overrides,
    }}


def node(zone="a", cpu="2", taints=None):
    taints = taints or []
    return {
        "allocatableCpu": cpu,
        "allocatableMemory": "4Gi",
        "unschedulable": False,
        "nodeLabels": {"zone": zone},
        "nodeTaints": taints,
        "taintCount": len(taints),
    }


def assess(resource, nodes, complete=True):
    return evaluate_combined_placement(
        resource, nodes, inventory_complete=complete
    )


def test_same_node_matches_all_observed_constraints():
    result = assess(workload(), [node()])
    assert result["status"] == "PARTIAL"
    assert result["candidateNodes"] == 1
    assert "remain unverified" in result["reason"]


def test_separate_nodes_cannot_satisfy_combined_constraints():
    result = assess(workload(), [
        node(zone="a", cpu="100m"),
        node(zone="b", cpu="4"),
    ])
    assert result["candidateNodes"] == 0
    assert result["status"] == "PENDING_EVIDENCE"


def test_init_container_request_floor():
    result = observed_pod_request_floor(
        workload(initContainers=[container("2", "2Gi")])
    )
    assert result["cpu"] == "2000m"
    assert result["memory"] == str(2 * 1024**3)


def test_init_container_requirements_affect_candidates():
    result = assess(
        workload(initContainers=[container("4", "2Gi")]),
        [node(cpu="2")]
    )
    assert result["candidateNodes"] == 0


def test_missing_init_requests_remain_pending():
    result = assess(
        workload(initContainers=[{}]), [node()]
    )
    assert result["status"] == "PENDING_EVIDENCE"


def test_incomplete_selector_values_remain_pending():
    result = assess(
        workload(nodeSelector=None, nodeSelectorKeys=["zone"]),
        [node()]
    )
    assert result["status"] == "PENDING_EVIDENCE"


def test_sanitized_equal_toleration_is_not_false_remediation():
    resource = workload(tolerations=[{
        "key": "dedicated",
        "operator": "Equal",
        "effect": "NoSchedule",
    }])

    target = node(taints=[{
        "key": "dedicated",
        "value": "apps",
        "effect": "NoSchedule",
    }])

    assert evaluate_node_tolerations(
        resource, [target], inventory_complete=True
    )["status"] == "PENDING_EVIDENCE"

    assert assess(
        resource, [target]
    )["status"] == "PENDING_EVIDENCE"


def test_hard_taint_prevents_candidate():
    target = node(taints=[{
        "key": "dedicated",
        "value": "apps",
        "effect": "NoSchedule",
    }])

    assert assess(
        workload(), [target]
    )["candidateNodes"] == 0


def test_stale_inventory_remains_pending():
    assert assess(
        workload(), [node()], complete=False
    )["status"] == "PENDING_EVIDENCE"


def test_affinity_does_not_establish_complete_placement():
    result = assess(
        workload(affinity={"podAntiAffinity": True}),
        [node()]
    )
    assert result["status"] == "PARTIAL"
    assert "affinity" in result["reason"]


def test_incomplete_target_taints_remain_pending():
    target = node()
    target["taintCount"] = 2

    result = assess(workload(), [target])
    assert result["status"] == "PENDING_EVIDENCE"
    assert result["unverifiedNodes"] == 1
