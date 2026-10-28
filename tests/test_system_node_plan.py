import ast
import json
from copy import deepcopy
from pathlib import Path

import pytest


def functions():
    """Load policy functions without running the runner's AWS job entrypoint."""
    path = Path(__file__).parents[1] / "provisioning/runner/runner.py"
    tree = ast.parse(path.read_text())
    module = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)], type_ignores=[])
    namespace = {"json": json}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


def inputs():
    request = {"configuration": {"endpointAccess": "PRIVATE", "nodeGroups": [
        {"name": "system", "purpose": "SYSTEM"},
        {"name": "apps", "purpose": "APPLICATION"},
    ]}}
    after = {"node_group_name": "system", "labels": {
        "navigan.io/platform-services": "true", "navigan.io/node-purpose": "system"
    }, "taint": [{"key": "navigan.io/system-only", "value": "true", "effect": "NO_SCHEDULE"}],
        "scaling_config": [{"min_size": 2, "desired_size": 2, "max_size": 4}]}
    plan = {"resource_changes": [{"type": "aws_eks_node_group",
        "address": 'aws_eks_node_group.this["system"]',
        "change": {"actions": ["create"], "after": after}}]}
    return plan, request, after


@pytest.mark.parametrize("actions", [["create"], ["update"], ["no-op"]])
def test_protected_system_pool_passes_without_requiring_application_labels(actions):
    plan, request, _ = inputs()
    plan["resource_changes"][0]["change"]["actions"] = actions
    assert functions()["security_scan"](plan, request)["status"] == "PASSED"


@pytest.mark.parametrize("fault", ["labels", "label_value", "purpose", "taint", "taint_effect", "min", "desired", "missing", "address", "name"])
def test_unprotected_plan_cannot_be_certified(fault):
    plan, request, after = inputs()
    if fault == "labels":
        after["labels"] = {}
    elif fault == "label_value":
        after["labels"]["navigan.io/platform-services"] = "false"
    elif fault == "purpose":
        after["labels"]["navigan.io/node-purpose"] = "application"
    elif fault == "taint":
        after["taint"] = []
    elif fault == "taint_effect":
        after["taint"][0]["effect"] = "PREFER_NO_SCHEDULE"
    elif fault in {"min", "desired"}:
        after["scaling_config"][0][fault + "_size"] = 0
    elif fault == "address":
        plan["resource_changes"][0]["address"] = 'module.unrelated.aws_eks_node_group.this["system"]'
    elif fault == "name":
        after["node_group_name"] = "different-group"
    else:
        plan["resource_changes"] = []
    scan = functions()["security_scan"](plan, request)
    assert scan["status"] == "FAILED"
    assert scan["findings"][0]["rule"] == "PROTECTED_SYSTEM_NODE_GROUP"


def test_legacy_purpose_default_is_checked_but_explicit_adopted_group_is_not_managed():
    plan, request, after = inputs()
    request["configuration"]["nodeGroups"][0].pop("purpose")
    assert not functions()["system_node_findings"](plan, request)
    after["labels"] = {}
    assert functions()["system_node_findings"](plan, request)
    request["configuration"]["nodeGroups"][0]["managementMode"] = "ADOPTED"
    assert not functions()["system_node_findings"](plan, request)
