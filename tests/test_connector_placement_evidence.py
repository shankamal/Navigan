"""Connector payload accepts optional bounded read-only placement observations."""
import pytest
from pydantic import ValidationError

from navigan.modules.cluster_management.connector_handler import RuntimeResourceItem


def _node(**extra):
    return dict(kind="Node", name="node-a", status="Ready", ready=1,
                desired=1, restarts=0, **extra)


def test_connector_preserves_observed_node_labels_and_taints():
    item = RuntimeResourceItem.model_validate(_node(
        nodeLabels={"topology.kubernetes.io/zone": "ap-south-1a"},
        nodeTaints=[{"key": "dedicated", "value": "system", "effect": "NoSchedule"}],
        apiVersion="v1",
    ))
    observed = item.model_dump()
    assert observed["nodeLabels"]["topology.kubernetes.io/zone"] == "ap-south-1a"
    assert observed["nodeTaints"][0]["effect"] == "NoSchedule"


def test_legacy_runtime_node_remains_compatible():
    item = RuntimeResourceItem.model_validate(_node())
    assert item.nodeLabels is None
    assert item.nodeTaints is None


def test_oversized_labels_rejected():
    with pytest.raises(ValidationError):
        RuntimeResourceItem.model_validate(_node(nodeLabels={
            f"example.com/key-{i}": str(i) for i in range(101)
        }))
