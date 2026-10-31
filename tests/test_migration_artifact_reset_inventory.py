import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

spec=importlib.util.spec_from_file_location("artifact_reset",Path(__file__).parents[1]/"scripts/prepare-migration-artifact-reset.py")
reset=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)
CID="CUS-"+"a"*32
MID="MIG-"+"b"*32
WID="AWS-"+"c"*32
KEY=f"customers/{CID}/migrations/{MID}/workspaces/{WID}/images/original.tar"


def test_proposed_folder_names_are_readable_safe_and_bound_to_unique_ids():
    result=reset.proposed_root({"customer_id":CID,"migration_id":MID,"customer_name":"Db Schenker / India",
                                "name":"DBS_Migration Assessment / .. / Prod"})
    assert result=="navigan/customers/db-schenker-india--aaaaaaaaaaaa/migrations/dbs-migration-assessment-prod--bbbbbbbbbbbb/"
    assert ".." not in result and " " not in result
    with pytest.raises(ValueError):
        reset.proposed_root({"customer_id":"../other","migration_id":MID})


def test_seeded_customer_and_assessment_ids_have_stable_distinct_roots():
    sample={"customer_id":"CUS-DEMO-0001","migration_id":"MIG-DEMO-0001",
            "customer_name":"Demo customer","name":"Demo migration"}
    root=reset.proposed_root(sample)
    assert root==reset.proposed_root(sample)
    assert root.startswith("navigan/customers/demo-customer--")
    assert root!=reset.proposed_root({**sample,"customer_id":"CUS-DEMO-0002"})
    assert root!=reset.proposed_root({**sample,"migration_id":"MIG-DEMO-0002"})


def test_inventory_includes_exact_versions_markers_uploads_and_preserves_unrelated_keys():
    s3=Mock()
    s3.get_bucket_versioning.return_value={"Status":"Enabled"}
    objects=[{"Versions":[{"Key":KEY,"VersionId":"old","Size":123}],"IsTruncated":True},
             {"Versions":[{"Key":KEY,"VersionId":"new","Size":456},
                          {"Key":KEY.replace(MID,"MIG-"+"d"*32),"VersionId":"other","Size":50},
                          {"Key":"customers/keep-me.txt","VersionId":"protected","Size":20}],
              "DeleteMarkers":[{"Key":KEY,"VersionId":"marker"}]}]
    s3.get_paginator.side_effect=lambda name:SimpleNamespace(paginate=Mock(return_value=(objects if name=="list_object_versions" else [
        {"Uploads":[{"Key":KEY,"UploadId":"upload-one"},{"Key":"customers/unrelated","UploadId":"protected"}]}])))
    result=reset.bucket_inventory(SimpleNamespace(client=lambda _:s3),"bucket",{(CID,MID)})
    assert {v["versionId"] for v in result["candidateVersions"]}=={"old","new","marker"}
    assert len(result["preservedVersions"])==2
    assert result["candidateUploads"]==[{"key":KEY,"uploadId":"upload-one"}]
    assert sum(v["bytes"] for v in result["candidateVersions"])==579
    assert {c[0] for c in s3.method_calls}<={"get_bucket_versioning","get_paginator"}


def test_unknown_identity_and_non_migration_keys_never_become_candidates():
    for key in ("customers/CUS-other/migrations/"+MID+"/workspaces/"+WID+"/data",
                f"customers/{CID}/migrations/{MID}/inventory/data.json",
                f"customers/{CID}/clusters/cluster/data",
                f"customers/{CID}/migrations/{MID}/workspaces/../secrets"):
        s3=Mock()
        s3.get_paginator.side_effect=lambda name:SimpleNamespace(paginate=lambda **kw:[
            {"Versions":[{"Key":key,"VersionId":"one","Size":1}]}] if name=="list_object_versions" else [])
        result=reset.bucket_inventory(SimpleNamespace(client=lambda _:s3),"bucket",{(CID,MID)})
        assert result["candidateVersions"]==[]
        assert len(result["preservedVersions"])==1


def test_database_inventory_only_issues_selects_and_paginates_assessments():
    data=Mock()
    first=[{"migration_id":f"MIG-{i:032x}","customer_id":CID,"name":"Example"} for i in range(200)]
    data.execute_statement.side_effect=[{"formattedRecords":json.dumps(first)}, {"formattedRecords":"[]"},
        {"formattedRecords":json.dumps([{"workspaces":2,"artifacts":7,"collection_jobs":3,
                                        "active_collection_jobs":1,"active_source_recoveries":0}])},
                                      {"formattedRecords":"[]"}]
    result=reset.database_inventory(SimpleNamespace(client=lambda _:data),
        {"secretArn":"private-reference","database":"navigan"},{"DBClusterArn":"cluster"})
    assert len(result["assessments"])==200 and result["active_collection_jobs"]==1
    assert data.execute_statement.call_args_list[1].kwargs["parameters"][0]["value"]["stringValue"]==first[-1]["migration_id"]
    assert all(c.kwargs["sql"].startswith("SELECT ") for c in data.execute_statement.call_args_list)
    assert "private-reference" not in json.dumps(result)


def session(account=reset.ACCOUNT):
    sts=Mock();sts.get_caller_identity.return_value={"Account":account}
    rds=Mock();rds.describe_db_clusters.return_value={"DBClusters":[{
        "DBClusterArn":f"arn:aws:rds:{reset.REGION}:{reset.ACCOUNT}:cluster:db","Status":"available"}]}
    rds.get_paginator.side_effect=lambda name:SimpleNamespace(paginate=lambda **kw:[
        {"DBProxies":[{"Endpoint":"proxy","DBProxyName":"proxy-one","Status":"available"}]}] if name=="describe_db_proxies" else [
        {"Targets":[{"Type":"RDS_INSTANCE","TargetHealth":{"State":"AVAILABLE"}}]}])
    return SimpleNamespace(client=lambda name:sts if name=="sts" else rds),sts,rds


def test_prepare_requires_expected_account_before_resource_reads():
    sdk,sts,rds=session("111111111111")
    with pytest.raises(RuntimeError,match="Unexpected AWS account"):
        reset.prepare(sdk)
    rds.describe_db_clusters.assert_not_called()


def test_database_host_can_be_direct_aurora_without_any_rds_proxy():
    rds=Mock()
    result=reset.connection_inventory(rds,"writer.example",{"Endpoint":"writer.example","ReaderEndpoint":"reader.example","Status":"available"},[],[])
    assert result=={"kind":"AURORA_WRITER","host":"writer.example","status":"available","writable":True}
    rds.get_paginator.assert_not_called()
    assert reset.connection_inventory(rds,"reader.example",{"ReaderEndpoint":"reader.example","Status":"available"},[],[])["writable"] is False


def test_instance_endpoint_and_unknown_host_are_not_reported_as_missing_proxy():
    rds=Mock()
    instance={"Endpoint":{"Address":"instance.example"},"DBInstanceStatus":"available","DBInstanceIdentifier":"db-instance"}
    assert reset.connection_inventory(rds,"instance.example",{},[],[instance])["kind"]=="RDS_INSTANCE"
    result=reset.connection_inventory(rds,"custom.example",{},[],[])
    assert result["kind"]=="UNRESOLVED" and "errorCode" not in result


def test_seeded_assessment_legacy_objects_are_only_scanned_for_verified_identity():
    cid,mid="CUS-DEMO-0001","MIG-DEMO-0001"
    key=f"customers/{cid}/migrations/{mid}/workspaces/{WID}/images/archive"
    s3=Mock()
    s3.get_paginator.side_effect=lambda name:SimpleNamespace(paginate=lambda **kw:[
        {"Versions":[{"Key":key,"VersionId":"one","Size":3}]}] if name=="list_object_versions" else [])
    sdk=SimpleNamespace(client=lambda _:s3)
    assert len(reset.bucket_inventory(sdk,"bucket",{(cid,mid)})["candidateVersions"])==1
    assert reset.bucket_inventory(sdk,"bucket",{(cid,MID)})["candidateVersions"]==[]


def test_source_recovery_inspects_status_without_printing_outputs_or_starting_commands():
    data,ssm=Mock(),Mock()
    data.execute_statement.side_effect=[{"formattedRecords":"[]"},{"formattedRecords":json.dumps([{
        "active_source_recoveries":1,"active_collection_jobs":0}])},{"formattedRecords":json.dumps([{
        "source_cluster_id":"SRC-one","migration_id":MID,"job_id":"REC-one","phase":"EXPORT",
        "command_id":"command-one","managed_instance_id":"i-one","source_account":reset.ACCOUNT}])}]
    ssm.get_command_invocation.return_value={"Status":"Success","StandardOutputContent":"private output","StandardErrorContent":"private error"}
    sdk=SimpleNamespace(client=lambda name,**kw:data if name=="rds-data" else ssm)
    inventory=reset.database_inventory(sdk,{"secretArn":"private-reference","database":"navigan"},{"DBClusterArn":"cluster"})
    assert inventory["sourceRecoveryDetails"][0]["commandStatus"]=="Success"
    assert "private" not in json.dumps(inventory)
    assert [c[0] for c in ssm.method_calls]==["get_command_invocation"]


def test_one_naming_failure_does_not_drop_that_environments_storage_inventory(monkeypatch):
    sdk,_,_=session()
    monkeypatch.setattr(reset,"settings",lambda _,parent,database:{"parent":parent,"database":database,
        "secretArn":"private-reference","proxyHost":"proxy","buckets":[database+"-bucket"]})
    monkeypatch.setattr(reset,"database_inventory",lambda *args:{"assessments":[{"customer_id":"../unknown","migration_id":MID}],
        "active_collection_jobs":0,"active_source_recoveries":0})
    scan=Mock(side_effect=lambda _,bucket,ids:{"bucket":bucket,"candidateVersions":[]})
    monkeypatch.setattr(reset,"bucket_inventory",scan)
    plan=reset.prepare(sdk)
    assert len(plan["buckets"])==2
    assert plan["environments"]["dev"]["inventory"]["assessments"][0]["namingErrorCode"]=="INVALID_ARTIFACT_IDENTITY"
    assert reset.summary(plan)["environments"]["dev"]["namingErrors"]==[{"migrationId":MID,"code":"INVALID_ARTIFACT_IDENTITY"}]


def test_collector_drift_check_compares_existing_api_bindings_without_reading_secrets():
    cfn,lam,ecs=Mock(),Mock(),Mock()
    expected={"DB_NAME":"navigan","DB_PROXY_HOST":"writer.example","DB_SECRET_ARN":"private-reference","DB_PORT":None}
    cfn.describe_stacks.side_effect=[{"Stacks":[{"Outputs":[{"OutputKey":"WorkerName","OutputValue":"worker"}]}]},
        {"Stacks":[{"Outputs":[{"OutputKey":"WorkerServiceName","OutputValue":"images"}],
                    "Parameters":[{"ParameterKey":"ClusterArn","ParameterValue":"cluster"}]}]}]
    lam.get_function_configuration.return_value={"Environment":{"Variables":{**expected,"DB_PROXY_HOST":"old.example"}},
        "VpcConfig":{"SubnetIds":["subnet"],"SecurityGroupIds":["sg"]}}
    ecs.describe_services.return_value={"services":[{"taskDefinition":"task","networkConfiguration":{"awsvpcConfiguration":{
        "subnets":["subnet"],"securityGroups":["sg"]}}}]}
    ecs.describe_task_definition.return_value={"taskDefinition":{"containerDefinitions":[{"name":"collector","environment":[
        {"name":k,"value":v} for k,v in expected.items() if v is not None]}]}}
    sdk=SimpleNamespace(client=lambda name:{"cloudformation":cfn,"lambda":lam,"ecs":ecs}[name])
    result=reset.collector_inventory(sdk,{"parent":"prod","comparisonValues":expected,
        "network":{"SubnetIds":["subnet"],"SecurityGroupIds":["sg"]}})
    assert result["repository"]=={"runtimeDifferences":["DB_PROXY_HOST"],"networkMatchesApi":True}
    assert result["images"]=={"runtimeDifferences":[],"networkMatchesApi":True}
    assert "private-reference" not in json.dumps(result)


def test_prepare_is_review_only_even_with_healthy_database_and_redacts_secret_reference(monkeypatch):
    sdk,_,_=session()
    monkeypatch.setattr(reset,"settings",lambda _,parent,database:{"parent":parent,"database":database,
        "secretArn":"never-print-this","proxyHost":"proxy","buckets":[database+"-workspace"]})
    monkeypatch.setattr(reset,"database_inventory",lambda *args:{"assessments":[{"customer_id":CID,"migration_id":MID}],
        "workspaces":1,"artifacts":1,"collection_jobs":0,"active_collection_jobs":0,"active_source_recoveries":0})
    monkeypatch.setattr(reset,"bucket_inventory",lambda _,bucket,ids:{"bucket":bucket,"candidateVersions":[
        {"key":KEY,"versionId":"one","bytes":1}],"candidateUploads":[],"preservedVersions":[]})
    plan=reset.prepare(sdk)
    assert set(plan["environments"])=={"dev","prod"}
    assert len(plan["buckets"])==2 and plan["readyToDelete"] is False
    assert "never-print-this" not in json.dumps(plan)
    assert "assessments" not in json.dumps(reset.summary(plan))
    assert reset.summary(plan)["environments"]["prod"]["assessmentCount"]==1


def test_failed_environment_inventory_blocks_cleanup_without_guessing_shared_bucket_scope(monkeypatch):
    sdk,_,_=session()
    monkeypatch.setattr(reset,"settings",lambda _,parent,database:{"parent":parent,"database":database,
        "secretArn":"private-reference","proxyHost":"proxy","buckets":["shared-bucket"]})
    def inventory(_,binding,cluster):
        if binding["database"]=="navigan":
            raise RuntimeError("private exception details")
        return {"assessments":[{"customer_id":CID,"migration_id":MID}],"active_collection_jobs":2,"active_source_recoveries":1}
    monkeypatch.setattr(reset,"database_inventory",inventory)
    scan=Mock(return_value={"bucket":"shared-bucket","candidateVersions":[]})
    monkeypatch.setattr(reset,"bucket_inventory",scan)
    plan=reset.prepare(sdk)
    assert plan["readyToDelete"] is False
    assert plan["environments"]["prod"]["errorCode"]=="RuntimeError"
    assert scan.call_args.args[2]=={(CID,MID)}
    assert "private exception details" not in json.dumps(plan)
    assert any("prod: database/runtime inventory incomplete" in b for b in plan["blockers"])
