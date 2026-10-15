from navigan.modules.migration_management.scheduling_evidence import evaluate_node_tolerations

NODE = [{"unschedulable": False, "nodeTaints": [
    {"key": "dedicated", "value": "apps", "effect": "NoSchedule"}
]}]


def test_matching_toleration_only_partially_verifies():
    resource = {"pod": {"tolerations": [{"key": "dedicated", "value": "apps", "operator": "Equal", "effect": "NoSchedule"}]}}
    result = evaluate_node_tolerations(resource, NODE, inventory_complete=True)
    assert result["status"] == "PARTIAL"


def test_untolerated_hard_taint_requires_remediation():
    result = evaluate_node_tolerations({"pod": {"tolerations": []}}, NODE, inventory_complete=True)
    assert result["status"] == "REMEDIATION_REQUIRED"


def test_missing_details_never_create_false_remediation():
    resource = {"pod": {"tolerations": []}}
    assert evaluate_node_tolerations(resource, [{"unschedulable": False}], inventory_complete=True)["status"] == "PENDING_EVIDENCE"
    assert evaluate_node_tolerations(resource, NODE, inventory_complete=False)["status"] == "PENDING_EVIDENCE"


def test_preferred_taint_does_not_block_scheduling():
    node = [{"unschedulable": False, "nodeTaints": [
        {"key": "capacity", "value": "spot", "effect": "PreferNoSchedule"}
    ]}]
    assert evaluate_node_tolerations({"pod": {"tolerations": []}}, node, inventory_complete=True)["status"] == "PARTIAL"
