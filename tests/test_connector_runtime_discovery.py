"""Actual in-cluster collector emits validated placement evidence."""
import importlib.util
from pathlib import Path

from navigan.modules.cluster_management.connector_handler import RuntimeInventory


def test_runtime_inventory_collects_node_labels_and_taints(monkeypatch):
    agent_path = Path(__file__).resolve().parents[1] / "connector" / "agent.py"
    spec = importlib.util.spec_from_file_location("navigan_cluster_agent_test", agent_path)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)

    node = {
        "metadata": {"name": "node-a", "labels": {"zone": "a"}},
        "spec": {"unschedulable": False,
                 "taints": [{"key": "dedicated", "value": "apps", "effect": "NoSchedule"}]},
        "status": {"allocatable": {"cpu": "2", "memory": "4Gi"},
                   "conditions": [{"type": "Ready", "status": "True"}]},
    }

    def request(path):
        if path == "/api/v1/nodes":
            return {"items": [node]}
        if path.endswith("/storageclasses") or path.endswith("/csidrivers"):
            return {"items": []}
        if path == "/api/v1" or path == "/apis/apps/v1":
            return {"groupVersion": "v1" if path == "/api/v1" else "apps/v1",
                    "resources": ([{"name": "pods", "kind": "Pod"}]
                                  if path == "/api/v1" else [{"name": "deployments", "kind": "Deployment"}])}
        return {"items": []}

    monkeypatch.setattr(agent, "kubernetes_request", request)
    payload = agent.runtime_inventory()
    validated = RuntimeInventory.model_validate(payload)
    observed = next(item for item in validated.resources if item.kind == "Node")
    assert observed.nodeLabels == {"zone": "a"}
    assert observed.nodeTaints == [{"key": "dedicated", "value": "apps", "effect": "NoSchedule"}]
    assert observed.allocatableCpu == "2"

    assert payload["metrics"]["apiKind_coreV1_Pod"] == 1
    assert payload["metrics"]["apiKind_coreV1_Service"] == 0
    assert payload["metrics"]["apiKind_appsV1_Deployment"] == 1
