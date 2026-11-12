import importlib.util
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).parents[1]


def load_release():
    path = ROOT / "scripts/deploy-eks-upgrade-readiness-prod.py"
    spec = importlib.util.spec_from_file_location("upgrade_readiness_release", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_customer_role_policy_is_read_only_and_complete():
    policy = json.loads(
        (ROOT / "infrastructure/bootstrap/eks-upgrade-readiness-read-policy.json").read_text()
    )
    actions = set(policy["Statement"][0]["Action"])

    assert actions == {
        "eks:DescribeAddon",
        "eks:DescribeAddonVersions",
        "eks:DescribeCluster",
        "eks:DescribeClusterVersions",
        "eks:DescribeInsight",
        "eks:DescribeNodegroup",
        "eks:DescribeUpdate",
        "eks:ListAddons",
        "eks:ListInsights",
        "eks:ListNodegroups",
        "eks:ListUpdates",
    }
    assert not any(
        action.split(":", 1)[1].startswith(("Create", "Delete", "Update"))
        for action in actions
    )


def test_release_patches_only_handler_and_adds_discovery_module(tmp_path):
    release = load_release()
    desired = (ROOT / "src/navigan/modules/cluster_management/handler.py").read_text()
    old = desired.replace(
        "from .upgrade_readiness import EksUpgradeDiscovery\n", ""
    ).replace('        "upgrade-readiness",\n', "").replace(
        '                elif action == "upgrade-readiness":\n'
        "                    _, environment = repo.pinned_environment_snapshot(\n"
        '                        row["environment_id"], row["environment_approved_version"]\n'
        "                    )\n"
        "                    value = EksUpgradeDiscovery().discover(row, environment)\n",
        "",
    )
    source = tmp_path / "old.zip"
    target = tmp_path / "new.zip"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("navigan/modules/cluster_management/handler.py", old)
        package.writestr("navigan/shared/errors.py", "class ApiError(Exception): pass\n")

    release.package(source, target)

    with zipfile.ZipFile(target) as package:
        assert package.read("navigan/modules/cluster_management/handler.py").decode() == desired
        assert package.read(
            "navigan/modules/cluster_management/upgrade_readiness.py"
        ) == (ROOT / "src/navigan/modules/cluster_management/upgrade_readiness.py").read_bytes()
        assert package.read("navigan/shared/errors.py") == b"class ApiError(Exception): pass\n"


def test_release_patches_crlf_deployed_handler_without_promoting_other_source_changes():
    release = load_release()
    desired = (ROOT / "src/navigan/modules/cluster_management/handler.py").read_text()
    old = desired.replace(
        "from .upgrade_readiness import EksUpgradeDiscovery\n", ""
    ).replace('        "upgrade-readiness",\n', "").replace(
        '                elif action == "upgrade-readiness":\n'
        "                    _, environment = repo.pinned_environment_snapshot(\n"
        '                        row["environment_id"], row["environment_approved_version"]\n'
        "                    )\n"
        "                    value = EksUpgradeDiscovery().discover(row, environment)\n",
        "",
    )
    old = old.replace(
        "from .bootstrap_status import refresh_installer_status\n"
        "from .tool_access import resolve_tool_access\n",
        "from .tool_access import resolve_tool_access\n"
        "from .bootstrap_status import refresh_installer_status\n",
    ).replace(
        '"""JWT-protected Cluster Management API. Terraform executions are asynchronous."""\n',
        '"""JWT-protected Cluster Management API. Terraform executions are asynchronous."""\n'
        "# deployed-only-sentinel\n",
    )
    old = old.replace("\n", "\r\n")

    patched = release.patch_handler(old)

    assert "\r\n" in patched
    assert "# deployed-only-sentinel\r\n" in patched
    assert patched.index("from .tool_access") < patched.index("from .bootstrap_status")
    assert patched.count("from .upgrade_readiness import EksUpgradeDiscovery") == 1
    assert patched.count('        "upgrade-readiness",') == 1
    assert patched.count('                elif action == "upgrade-readiness":') == 1
