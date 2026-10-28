from unittest.mock import Mock
from navigan.modules.migration_management.target_discovery import discover_eks_control_plane


def test_eks_discovery_reads_control_plane_only():
    eks = Mock()
    eks.describe_cluster.return_value = {"cluster": {
        "name": "demo-eks", "version": "1.30", "status": "ACTIVE",
        "arn": "arn:aws:eks:ap-south-1:111111111111:cluster/demo-eks",
        "resourcesVpcConfig": {"endpointPublicAccess": False, "endpointPrivateAccess": True},
    }}
    result = discover_eks_control_plane(name="demo-eks", region="ap-south-1", client=eks)
    eks.describe_cluster.assert_called_once_with(name="demo-eks")
    assert result["clusterStatus"] == "ACTIVE"
    assert result["evidenceLevel"] == "CONTROL_PLANE_ONLY"
    assert result["coverageComplete"] is False
    assert "StorageClass and CSI compatibility" in result["unverified"]


def test_eks_discovery_rejects_unexpected_cluster():
    eks = Mock()
    eks.describe_cluster.return_value = {"cluster": {"name": "other"}}
    import pytest
    with pytest.raises(ValueError):
        discover_eks_control_plane(name="demo-eks", region="ap-south-1", client=eks)
