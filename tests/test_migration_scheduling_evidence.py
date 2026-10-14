from navigan.modules.migration_management.scheduling_evidence import (
    cpu_millicores, memory_bytes, evaluate_node_capacity,
)


def node(cpu="1930m", memory="7350Mi", unschedulable=False, taintCount=0):
    return {"allocatableCpu": cpu, "allocatableMemory": memory,
            "unschedulable": unschedulable, "taintCount": taintCount}


def test_quantity_conversion():
    assert cpu_millicores("2") == 2000
    assert cpu_millicores("250m") == 250
    assert cpu_millicores("bad") is None
    assert memory_bytes("1Gi") == 1024 ** 3
    assert memory_bytes("100Mi") == 100 * 1024 ** 2
    assert memory_bytes("bad") is None


def test_candidate_is_not_declared_directly_compatible():
    result = evaluate_node_capacity("500m", "1Gi", [node()], inventory_complete=True)
    assert result["status"] == "PARTIAL"
    assert result["candidateNodes"] == 1


def test_insufficient_allocatable_is_remediation_required_only_with_full_coverage():
    nodes = [node("250m", "512Mi")]
    assert evaluate_node_capacity("1", "1Gi", nodes, inventory_complete=True)["status"] == "REMEDIATION_REQUIRED"
    assert evaluate_node_capacity("1", "1Gi", nodes)["status"] == "PENDING_EVIDENCE"


def test_taints_and_cordon_do_not_false_block():
    assert evaluate_node_capacity("500m", "1Gi", [node(taintCount=1)], inventory_complete=True)["status"] == "PENDING_EVIDENCE"
    assert evaluate_node_capacity("500m", "1Gi", [node(unschedulable=True)], inventory_complete=True)["status"] == "PENDING_EVIDENCE"


def test_unknown_capacity_is_not_compatible():
    assert evaluate_node_capacity("500m", "1Gi", [{"allocatableCpu": "1"}], inventory_complete=True)["status"] == "PENDING_EVIDENCE"
    assert evaluate_node_capacity(None, "1Gi", [node()], inventory_complete=True)["status"] == "PENDING_EVIDENCE"
