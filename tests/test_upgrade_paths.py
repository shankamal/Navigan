import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import MagicMock
import pytest
from navigan.shared.access import EffectiveAccess, Scope
from navigan.shared.errors import ApiError
from navigan.modules.cluster_management.upgrade_paths import (
    ScopedEksUpgradePlans, CreateScopedUpgradePlan, sequential_path, validate_windows, utcnow,
)

class Eks:
    def __init__(self):
        self.version="1.34"; self.nodes=[{"name":"system","version":"1.34","status":"ACTIVE","healthIssues":[],"amiType":"AL2023_x86_64_STANDARD"}]
        self.addons=[{"name":"cni","version":"v1.0.0","status":"ACTIVE","healthIssues":[]}]
        self.writes=[]; self.update_status="Successful"; self.active=[]
        self.versions={v:["v1.0.0","v1.1.0"] for v in ["1.34","1.35","1.36","1.37"]}
    def describe_cluster(self, **kwargs): return {"cluster":{"version":self.version,"status":"ACTIVE"}}
    def describe_addon_versions(self, addonName, kubernetesVersion, **kwargs):
        return {"addons":[{"addonVersions":[{"addonVersion":v,"compatibilities":[{"clusterVersion":kubernetesVersion,"defaultVersion":True}]} for v in self.versions[kubernetesVersion]]}]}
    def list_updates(self, **kwargs): return {"updateIds":[]}
    def describe_update(self, **kwargs): return {"update":{"id":"id","status":self.update_status}}
    def update_cluster_version(self, **kwargs): self.writes.append(("CONTROL_PLANE",kwargs));return {"update":{"id":"cp","status":"InProgress"}}
    def update_nodegroup_version(self, **kwargs): self.writes.append(("NODEGROUP",kwargs));return {"update":{"id":"node","status":"InProgress"}}
    def update_addon(self, **kwargs): self.writes.append(("ADDON",kwargs));return {"update":{"id":"addon","status":"InProgress"}}

class Discovery:
    def __init__(self, eks): self.eks=eks
    def client(self,*_): return self.eks,"ap-south-1"
    def _node_groups(self,*_): return deepcopy(self.eks.nodes)
    def _addons(self,*_): return deepcopy(self.eks.addons)
    def _versions(self,*_): return [{"version":v,"supportStatus":"STANDARD_SUPPORT"} for v in ["1.34","1.35","1.36","1.37"]]
    def _insights(self,*_): return []

@pytest.fixture
def service():
    eks=Eks(); repo=MagicMock()
    repo.get.return_value={
        "cluster_id":"CLU-one","cluster_name":"demo","customer_id":"CUS-one",
        "environment_id":"ENV-one","environment_approved_version":1,
        "configuration":{"kubernetesVersion":"1.34","nodeGroups":[]},
        "terraform_state_key":"customers/CUS-one/clusters/demo/terraform.tfstate",
        "terraform_module_version":"1.0.0","version":7,"status":"ACTIVE",
    }
    repo.pinned_environment_snapshot.return_value=({}, {"configuration":{}})
    repo.db.execute.return_value.fetchone.return_value=None
    provisioner=MagicMock()
    provisioner.bucket="artifacts"
    provisioner.start.return_value=("build-1","executions/CUS-one/CLU-one/run-1")
    access=EffectiveAccess("engineer","Engineer",0,frozenset({"cluster.upgrade.plan","cluster.upgrade.execute"}),(Scope("PLATFORM"),))
    return ScopedEksUpgradePlans(repo, access,"test",Discovery(eks),provisioner)

def payload(scope="CLUSTER",**changes):
    return {"upgradeScope":scope,"targetVersion":"1.37" if scope in {"CLUSTER","CONTROL_PLANE"} else None,"changeReason":"Apply supported upgrade",**changes}

def row(service, body=None):
    captured={}
    service._save=lambda value,create=False: captured.update(deepcopy(value))
    service.create("CLU-one",body or payload())
    return captured

def approve(plan, at):
    for step in plan["plan_spec"]["steps"]:
        step["window"]={"scheduledFor":at.isoformat(),"durationMinutes":120};at+=timedelta(days=1)
    plan.update(status="SCHEDULED",approved_by="architect",submitted_by="engineer")
    return plan

def test_sequential_path_rejects_gaps_and_downgrades(service):
    catalogue=service.discovery._versions()
    assert sequential_path("1.34","1.37",catalogue)==["1.35","1.36","1.37"]
    with pytest.raises(ApiError,match="intermediate"):
        sequential_path("1.34","1.37",[x for x in catalogue if x["version"]!="1.36"])
    with pytest.raises(ApiError,match="higher"):
        sequential_path("1.34","1.33",catalogue)

def test_draft_stores_complete_path_without_calling_update_api(service):
    p=row(service)
    assert [s["targetVersion"] for s in p["plan_spec"]["steps"]]==["1.35","1.36","1.37"]
    assert all([o["kind"] for o in s["operations"]]==["CONTROL_PLANE","NODEGROUP"] for s in p["plan_spec"]["steps"])
    assert all([o["stage"] for o in s["operations"]]==["CONTROL_PLANE","DATA_PLANE"] for s in p["plan_spec"]["steps"])
    assert service.discovery.eks.writes==[]
    assert "readinessEvidence" not in service.present(p)

def test_control_plane_only_scope_never_adds_node_groups_or_addons(service):
    p=row(service,payload("CONTROL_PLANE",targetVersion="1.35"))
    assert p["plan_spec"]["scope"]=="CONTROL_PLANE"
    assert p["plan_spec"]["nodeGroups"]==[]
    assert p["plan_spec"]["addonNames"]==[]
    assert [o["kind"] for o in p["plan_spec"]["steps"][0]["operations"]]==["CONTROL_PLANE"]
    assert service.discovery.eks.writes==[]

def test_control_plane_only_blocks_incompatible_installed_addon(service):
    service.discovery.eks.versions["1.35"]=["v1.1.0"]
    with pytest.raises(ApiError,match="managed add-on plan"):
        row(service,payload("CONTROL_PLANE",targetVersion="1.35"))
    assert service.discovery.eks.writes==[]

def test_node_only_scope_catches_up_without_control_plane_update(service):
    service.discovery.eks.version="1.35"
    p=row(service,payload("NODES",nodeGroups=["system"]))
    assert p["current_version"]==p["target_version"]=="1.35"
    assert [o["kind"] for o in p["plan_spec"]["steps"][0]["operations"]]==["NODEGROUP"]
    assert service.discovery.eks.writes==[]

def test_addon_only_scope_has_no_node_or_control_plane_operations(service):
    p=row(service,payload("ADDONS",addons={"cni":"v1.1.0"}))
    assert [o["kind"] for o in p["plan_spec"]["steps"][0]["operations"]]==["ADDON"]
    with pytest.raises(ApiError,match="compatible"):
        row(service,payload("ADDONS",addons={"cni":"v9.9.9"}))

def test_incompatible_addon_becomes_prerequisite_before_control_plane(service):
    service.discovery.eks.versions["1.35"]=["v1.1.0"]
    p=row(service,payload(targetVersion="1.35"))
    assert [o["kind"] for o in p["plan_spec"]["steps"][0]["operations"]]==["ADDON","CONTROL_PLANE","NODEGROUP"]
    assert [o["stage"] for o in p["plan_spec"]["steps"][0]["operations"]]==["PREREQUISITE_COMPONENTS","CONTROL_PLANE","DATA_PLANE"]
    service.discovery.eks.versions["1.35"]=["v2.0.0"]
    with pytest.raises(ApiError,match="compatible with both"):
        row(service,payload(targetVersion="1.35"))

def test_maker_permission_cannot_execute_and_expired_windows_never_call_aws(service):
    p=approve(row(service),utcnow()-timedelta(hours=3))
    with pytest.raises(ApiError,match="expired"):
        service._execute(p)
    assert service.discovery.eks.writes==[]
    service.access=EffectiveAccess("engineer","Engineer",0,frozenset({"cluster.upgrade.plan"}),(Scope("PLATFORM"),))
    with pytest.raises(ApiError) as error: service._execute(p)
    assert error.value.status==403

def test_full_platform_pauses_at_health_gates_before_next_stage(service):
    p=approve(row(service),utcnow()-timedelta(minutes=1))
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._execute(p);p=saved[-1]
    assert p["execution"]["startPreflight"]["status"]=="PASSED"
    assert p["execution"]["startPreflight"]["operatorId"]=="engineer"
    assert p["execution"]["startPreflight"]["approvedBy"]=="architect"
    assert p["execution"]["startPreflight"]["windowStartsAt"]==p["plan_spec"]["steps"][0]["window"]["scheduledFor"]
    assert p["execution"]["startPreflight"]["windowEndsAt"] > p["execution"]["startPreflight"]["windowStartsAt"]
    assert p["execution"]["startPreflight"]["firstStage"]=="CONTROL_PLANE"
    assert p["execution"]["startPreflight"]["controlPlaneVersion"]=="1.34"
    assert p["execution"]["startPreflight"]["upgradeInsightsPassing"] is True
    assert p["execution"]["startPreflight"]["applicationValidation"]=="OPERATOR_CONFIRMED_BEFORE_START"
    assert service.discovery.eks.writes[-1][0]=="CONTROL_PLANE"
    service.discovery.eks.version="1.35"
    service._refresh(p);p=saved[-1]
    assert p["status"]=="EXECUTING"
    assert p["execution"]["phase"]=="AWAITING_CONTROL_PLANE_HEALTH"
    assert p["execution"]["gate"]["nextStage"]=="DATA_PLANE"
    assert len(service.discovery.eks.writes)==1
    with pytest.raises(ApiError,match="explicitly continue"):
        service._refresh(p)
    service._continue(p);p=saved[-1]
    assert service.discovery.eks.writes[-1][0]=="NODEGROUP"
    assert service.discovery.eks.writes[-1][1].get("force") is None
    assert p["execution"]["gateHistory"][0]["afterStage"]=="CONTROL_PLANE"
    service.discovery.eks.nodes[0]["version"]="1.35"
    service._refresh(p);p=saved[-1]
    assert p["execution"]["phase"]=="AWAITING_DATA_PLANE_HEALTH"
    assert p["execution"]["gate"]["nextStage"]=="POST_VALIDATION"
    assert len(service.discovery.eks.writes)==2
    service._continue(p);p=saved[-1]
    assert p["status"]=="SCHEDULED" and p["execution"]["hopIndex"]==1
    assert len(p["execution"]["results"])==2
    assert len(p["execution"]["gateHistory"])==2
    with pytest.raises(ApiError,match="not started"):service._execute(p)
    assert len(service.discovery.eks.writes)==2

def test_health_gate_rechecks_live_state_before_continuing(service):
    p=approve(row(service,payload(targetVersion="1.35")),utcnow()-timedelta(minutes=1))
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._execute(p);p=saved[-1]
    service.discovery.eks.version="1.35"
    service._refresh(p);p=saved[-1]
    service.discovery.eks.nodes[0]["status"]="DEGRADED"
    with pytest.raises(ApiError,match="must be healthy"):
        service._continue(p)
    assert len(service.discovery.eks.writes)==1

def test_component_only_plans_do_not_use_full_platform_gate(service):
    service.discovery.eks.version="1.35"
    p=approve(row(service,payload("NODES",nodeGroups=["system"])),utcnow()-timedelta(minutes=1))
    service.discovery.eks.nodes[0]["version"]="1.34"
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._execute(p);p=saved[-1]
    service.discovery.eks.nodes[0]["version"]="1.35"
    service._refresh(p);p=saved[-1]
    assert p["status"]=="SUCCEEDED"
    assert p["execution"]["phase"]=="POST_VALIDATION"
    with pytest.raises(ApiError,match="full platform"):
        service._continue({**p,"status":"EXECUTING"})

def test_final_success_records_provider_post_validation(service):
    service.discovery.eks.version="1.35"
    p=approve(row(service,payload("NODES",nodeGroups=["system"])),utcnow()-timedelta(minutes=1))
    service.discovery.eks.nodes[0]["version"]="1.34"
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._execute(p);p=saved[-1]
    service.discovery.eks.nodes[0]["version"]="1.35"
    service._refresh(p);p=saved[-1]
    assert p["status"]=="SUCCEEDED"
    assert p["execution"]["phase"]=="POST_VALIDATION"
    assert p["execution"]["postValidation"]["status"]=="PASSED"
    assert p["execution"]["postValidation"]["controlPlaneVersion"]=="1.35"
    assert p["execution"]["postValidation"]["applicationValidation"]=="OPERATOR_VERIFICATION_REQUIRED"

def successful_reconciliation_plan(service):
    p=row(service,payload(targetVersion="1.35"))
    p.update(
        status="SUCCEEDED",
        execution={
            "phase":"POST_VALIDATION",
            "postValidation":{"status":"PASSED"},
        },
    )
    service.discovery.eks.version="1.35"
    service.discovery.eks.nodes[0]["version"]="1.35"
    return p


def test_iac_reconciliation_blocks_missing_backend_state_before_plan(service):
    p=successful_reconciliation_plan(service)
    service.provisioner.state_exists.return_value=False
    with pytest.raises(ApiError) as error:
        service._start_iac_reconciliation(p)
    assert error.value.code=="TERRAFORM_STATE_NOT_FOUND"
    service.provisioner.start.assert_not_called()
    service.repo.save.assert_not_called()


def test_iac_reconciliation_starts_plan_only_after_provider_success(service):
    p=successful_reconciliation_plan(service)
    service.provisioner.state_exists.return_value=True
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._start_iac_reconciliation(p)
    result=saved[-1]["execution"]["iacReconciliation"]
    assert result["status"]=="PLAN_RUNNING"
    assert result["desiredVersionBefore"]=="1.34"
    assert result["targetVersion"]=="1.35"
    candidate=service.provisioner.start.call_args.args[1]
    assert service.provisioner.start.call_args.args[0]=="plan"
    assert candidate["configuration"]["kubernetesVersion"]=="1.35"
    assert service.repo.get.return_value["configuration"]["kubernetesVersion"]=="1.34"
    service.repo.save.assert_not_called()


def test_iac_reconciliation_blocks_any_non_noop_terraform_plan(service):
    p=successful_reconciliation_plan(service)
    _, candidate=service._reconciliation_candidate(p)
    p["execution"]["iacReconciliation"]={
        "status":"PLAN_RUNNING","planBuildId":"build-1",
        "planArtifactPrefix":"executions/CUS-one/CLU-one/run-1",
        "targetVersion":"1.35","desiredVersionBefore":"1.34",
        "candidateFingerprint":service._reconciliation_candidate_fingerprint(candidate),
    }
    service.provisioner.codebuild.batch_get_builds.return_value={
        "builds":[{"buildStatus":"SUCCEEDED"}]
    }
    body=MagicMock()
    body.read.return_value=json.dumps({
        "success":True,"planSha256":"abc",
        "planSummary":{"actions":{"update":1}},
        "certification":{"status":"PASSED"},
        "securityScan":{"status":"PASSED"},
    }).encode()
    service.provisioner.s3.get_object.return_value={"Body":body}
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._refresh_iac_reconciliation(p)
    reconciliation=saved[-1]["execution"]["iacReconciliation"]
    assert reconciliation["status"]=="BLOCKED"
    assert reconciliation["failureCode"]=="UNEXPECTED_TERRAFORM_CHANGES"
    service.repo.save.assert_not_called()


def test_iac_reconciliation_certifies_noop_then_persists_only_after_apply(service):
    p=successful_reconciliation_plan(service)
    _, candidate=service._reconciliation_candidate(p)
    p["execution"]["iacReconciliation"]={
        "status":"PLAN_RUNNING","planBuildId":"build-1",
        "planArtifactPrefix":"executions/CUS-one/CLU-one/run-1",
        "targetVersion":"1.35","desiredVersionBefore":"1.34",
        "candidateFingerprint":service._reconciliation_candidate_fingerprint(candidate),
    }
    service.provisioner.codebuild.batch_get_builds.return_value={
        "builds":[{"buildStatus":"SUCCEEDED"}]
    }
    plan_body=MagicMock()
    plan_body.read.return_value=json.dumps({
        "success":True,"planSha256":"plan-sha",
        "planSummary":{"actions":{"no-op":4}},
        "certification":{"status":"PASSED"},
        "securityScan":{"status":"PASSED"},
    }).encode()
    service.provisioner.s3.get_object.return_value={"Body":plan_body}
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._refresh_iac_reconciliation(p);p=saved[-1]
    assert p["execution"]["iacReconciliation"]["status"]=="PLAN_READY"
    service.repo.save.assert_not_called()

    service.provisioner.start.return_value=("apply-1","executions/CUS-one/CLU-one/apply-1")
    service._apply_iac_reconciliation(p);p=saved[-1]
    assert p["execution"]["iacReconciliation"]["status"]=="APPLYING"
    candidate=service.provisioner.start.call_args.args[1]
    assert service.provisioner.start.call_args.args[0]=="apply"
    assert candidate["plan_artifact_key"].endswith("/terraform.tfplan")
    assert candidate["plan_sha256"]=="plan-sha"
    service.repo.save.assert_not_called()

    apply_body=MagicMock()
    apply_body.read.return_value=json.dumps({"success":True,"mode":"apply","outputs":{}}).encode()
    service.provisioner.s3.get_object.return_value={"Body":apply_body}
    service._refresh_iac_reconciliation(p)
    final=saved[-1]
    assert final["execution"]["phase"]=="IAC_SYNCHRONIZED"
    assert final["execution"]["iacReconciliation"]["status"]=="SYNCHRONIZED"
    reconciled=service.repo.save.call_args.args[0]
    assert reconciled["configuration"]["kubernetesVersion"]=="1.35"
    assert reconciled["version"]==8
    service.repo.record.assert_called_once()


def test_failed_stage_never_advances_to_node_update(service):
    p=approve(row(service),utcnow()-timedelta(minutes=1))
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._execute(p);p=saved[-1];service.discovery.eks.update_status="Failed"
    service._refresh(p)
    assert saved[-1]["status"]=="FAILED" and len(service.discovery.eks.writes)==1

def test_window_order_and_input_validation():
    with pytest.raises(ValueError,match="timezone"):
        CreateScopedUpgradePlan.model_validate(payload(hopWindows=[{"scheduledFor":"2026-12-01T10:00:00"}]))
    window={"scheduledFor":"2026-12-01T10:00:00Z","durationMinutes":120}
    with pytest.raises(ApiError,match="overlap"):
        validate_windows([{"window":window},{"window":window}],require_all=True)
    with pytest.raises(ApiError,match="every upgrade step"):
        validate_windows([{}],require_all=True)

def test_addon_minor_path_and_downgrade_guard(service):
    eks=service.discovery.eks
    eks.versions["1.34"]=["v1.0.0","v1.1.0","v1.2.0","v1.3.0"]
    p=row(service,payload("ADDONS",addons={"cni":"v1.3.0"}))
    assert [o["to"] for o in p["plan_spec"]["steps"][0]["operations"]]==["v1.1.0","v1.2.0","v1.3.0"]
    eks.versions["1.34"]=["v1.0.0","v1.3.0"]
    with pytest.raises(ApiError,match="intermediate"):
        row(service,payload("ADDONS",addons={"cni":"v1.3.0"}))
    eks.addons[0]["version"]="v1.3.0"
    with pytest.raises(ApiError,match="newer"):
        row(service,payload("ADDONS",addons={"cni":"v1.0.0"}))

def test_expired_window_stops_before_next_stage_after_health_gate(service):
    p=approve(row(service,payload(targetVersion="1.35")),utcnow()-timedelta(minutes=1))
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._execute(p);p=saved[-1]
    service.discovery.eks.version="1.35"
    p["plan_spec"]["steps"][0]["window"]["scheduledFor"]=(utcnow()-timedelta(hours=3)).isoformat()
    service._refresh(p);p=saved[-1]
    assert p["status"]=="EXECUTING"
    assert p["execution"]["phase"]=="AWAITING_CONTROL_PLANE_HEALTH"
    assert len(service.discovery.eks.writes)==1
    assert p["execution"]["results"][0]["status"]=="SUCCEEDED"
    service._continue(p)
    assert saved[-1]["status"]=="FAILED"
    assert len(service.discovery.eks.writes)==1

def test_drift_or_bad_insights_never_starts_provider_update(service):
    p=approve(row(service),utcnow()-timedelta(minutes=1))
    service.discovery.eks.nodes.append({"name":"new-node","version":"1.34","status":"ACTIVE"})
    with pytest.raises(ApiError,match="membership"):
        service._execute(p)
    service.discovery.eks.nodes.pop()
    service.discovery._insights=lambda *_:[{"status":"ERROR"}]
    with pytest.raises(ApiError,match="insights"):
        service._execute(p)
    assert service.discovery.eks.writes==[]

def test_submit_and_reschedule_keep_exact_approved_scope(service):
    p=row(service)
    service.get=lambda *_args,**_kwargs:p
    with pytest.raises(ApiError,match="every upgrade step"):
        service.change("CLU-one",p["plan_id"],"submit",{"version":1})
    windows=[{"scheduledFor":(utcnow()+timedelta(days=i+1)).isoformat(),"durationMinutes":120} for i in range(3)]
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    result=service.change("CLU-one",p["plan_id"],"reschedule",{"version":1,"hopWindows":windows})
    assert result["status"]=="DRAFT"
    assert saved[-1]["plan_spec"]["steps"][2]["window"]==windows[2]
    assert saved[-1]["plan_spec"]["scope"]=="CLUSTER"
    assert service.discovery.eks.writes==[]

def test_list_serializes_scoped_spec_without_legacy_empty_evidence(service):
    p=row(service,payload("ADDONS",addons={"cni":"v1.1.0"}))
    service.repo.db.execute.return_value.fetchall.return_value=[p]
    result=service.list("CLU-one")["items"][0]
    assert result["planSpec"]["scope"]=="ADDONS"
    assert "readinessEvidence" not in result

def test_legacy_rows_with_migrated_empty_spec_remain_readable(service):
    legacy={"plan_spec":{},"readiness_evidence":{"observedAt":"test"}}
    value=service.present(legacy)
    assert "planSpec" not in value and value["readinessEvidence"]==legacy["readiness_evidence"]

def test_read_failure_explains_customer_role_without_any_update(service):
    from botocore.exceptions import ClientError
    service.discovery.eks.describe_cluster=MagicMock(side_effect=ClientError({"Error":{"Code":"AccessDeniedException"}},"DescribeCluster"))
    with pytest.raises(ApiError,match="customer provisioning role") as error:
        service.options("CLU-one")
    assert error.value.code=="EKS_DISCOVERY_ACCESS_DENIED"
    assert service.discovery.eks.writes==[]

def test_cancel_preserves_completed_hop_history(service):
    p=row(service);p.update(status="SCHEDULED",execution={"completedHops":1,"results":[{"status":"SUCCEEDED"}]})
    service.get=lambda *_args,**_kwargs:p
    service._save=lambda *_args,**_kwargs:None
    result=service.change("CLU-one",p["plan_id"],"cancel",{"version":1,"reason":"Replan next window"})
    assert result["status"]=="CANCELLED"
    assert result["execution"]["completedHops"]==1
    assert result["execution"]["results"]==[{"status":"SUCCEEDED"}]

def test_control_plane_plan_requires_node_catchup_before_approval(service):
    service.discovery.eks.nodes[0]["version"]="1.33"
    with pytest.raises(ApiError,match="Align managed node groups"):
        row(service)
    p=row(service,payload("NODES",nodeGroups=["system"]))
    assert p["plan_spec"]["steps"][0]["operations"][0]["to"]=="1.34"


def test_engineer_executes_recorded_architect_self_approval_but_not_unrecorded_self_approval(service):
    p=approve(row(service),utcnow()-timedelta(minutes=1))
    p.update(created_by="architect",approved_by="architect")
    with pytest.raises(ApiError,match="policy record"):
        service._execute(p)
    assert service.discovery.eks.writes==[]
    p["execution"]={"approval":{"policy":"PLATFORM_ARCHITECT_SELF_APPROVAL_V1","actorId":"architect","role":"PLATFORM_ARCHITECT","selfApproved":True}}
    saved=[];service._save=lambda value,create=False:saved.append(deepcopy(value))
    service._execute(p)
    assert service.discovery.eks.writes[-1][0]=="CONTROL_PLANE"
    assert saved[-1]["execution"]["approval"]["selfApproved"] is True
