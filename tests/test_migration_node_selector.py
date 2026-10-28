from navigan.modules.migration_management.scheduling_evidence import evaluate_node_selector

NODES = [{"nodeLabels": {"zone": "a", "pool": "apps"}, "unschedulable": False},
         {"nodeLabels": {"zone": "b", "pool": "apps"}, "unschedulable": False}]


def test_exact_node_selector_match_remains_partial():
    result = evaluate_node_selector({"pod": {"nodeSelector": {"zone": "a"}}}, NODES,
                                    inventory_complete=True)
    assert result["status"] == "PARTIAL"
    assert result["candidateNodes"] == 1


def test_no_matching_node_requires_remediation():
    result = evaluate_node_selector({"pod": {"nodeSelector": {"zone": "c"}}}, NODES,
                                    inventory_complete=True)
    assert result["status"] == "REMEDIATION_REQUIRED"


def test_incomplete_nodes_are_not_false_blockers():
    result = evaluate_node_selector({"pod": {"nodeSelector": {"zone": "c"}}},
                                    [{"unschedulable": False}], inventory_complete=True)
    assert result["status"] == "PENDING_EVIDENCE"


def test_stale_target_is_not_a_false_blocker():
    result = evaluate_node_selector({"pod": {"nodeSelector": {"zone": "c"}}}, NODES,
                                    inventory_complete=False)
    assert result["status"] == "PENDING_EVIDENCE"
