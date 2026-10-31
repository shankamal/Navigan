import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("collection_audit", Path(__file__).parents[1] / "scripts/audit-prod-migration-collection.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
MID = "MIG-" + "a" * 32
WID = "AWS-" + "b" * 32


def session(*, account=audit.ACCOUNT, repository_error=False):
    calls = []

    def stack(**kw):
        name = kw["StackName"]
        if name.endswith("workspace-repositories"):
            if repository_error:
                raise RuntimeError("private diagnostic text")
            outputs = {"WorkerName": "repo-worker", "ScheduleName": "repo-schedule"}
            parameters = {}
        elif name.endswith("workspace-images"):
            outputs, parameters = {"WorkerServiceName": "image-worker"}, {"ClusterArn": "prod-cluster"}
        else:
            outputs, parameters = {"WorkspaceBucketName": "prod-bucket"}, {}
        return {"Stacks": [{"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in outputs.items()],
                            "Parameters": [{"ParameterKey": k, "ParameterValue": v} for k, v in parameters.items()]}]}

    def objects(**kw):
        if kw["Prefix"] == "customers/":
            return {"CommonPrefixes": [{"Prefix": "customers/CUS-one/"}]}
        assert MID in kw["Prefix"] and kw["ExpectedBucketOwner"] == audit.ACCOUNT
        return {"Contents": [{"Key": kw["Prefix"] + WID + "/" + key, "Size": size}
                             for key, size in (("workspace-manifest.json", 10), ("images/one.tar", 100))]}

    methods = {
        "get_caller_identity": lambda **kw: {"Account": account}, "describe_stacks": stack,
        "get_function_configuration": lambda **kw: {"FunctionArn": "repo-arn", "State": "Active", "LastUpdateStatus": "Successful",
                                                   "Environment": {"Variables": {"PRIVATE": "do-not-print"}}},
        "describe_rule": lambda **kw: {"State": "ENABLED"},
        "list_targets_by_rule": lambda **kw: {"Targets": [{"Arn": "repo-arn"}]},
        "get_metric_statistics": lambda **kw: {"Datapoints": [{"Sum": 2 if kw["MetricName"] == "Invocations" else 0}]},
        "describe_services": lambda **kw: {"services": [{"desiredCount": 1, "runningCount": 1, "pendingCount": 0}]},
        "list_commands": lambda **kw: {"Commands": [
            {"Comment": "Recover source artifact without changing workloads", "CommandId": "command-one", "Status": "Success", "Parameters": {"secret": "do-not-print"}},
            {"Comment": "Unrelated", "CommandId": "unrelated", "Status": "Success"}]},
        "list_objects_v2": objects,
    }

    class Client:
        def __getattr__(self, name):
            def invoke(**kw):
                calls.append(name)
                return methods[name](**kw)
            return invoke

    return SimpleNamespace(client=lambda name: Client()), calls


def test_read_only_scoped_audit_reports_workers_objects_without_secret_contents():
    sdk, calls = session()
    result = audit.collect(sdk, MID)
    assert result["readOnly"] is True and result["environment"] == "prod"
    assert result["repositoryCollector"]["targetMatchesWorker"] is True
    assert result["imageCollector"]["running"] == 1
    assert result["workspaceStorage"]["workspaces"] == [{"workspaceId": WID, "s3Uri":f"s3://prod-bucket/customers/CUS-one/migrations/{MID}/workspaces/{WID}/", "objects": 2, "bytes": 110,
                                                        "folders": {"workspace-manifest.json": 1, "images": 1}}]
    rendered = json.dumps(result)
    assert "do-not-print" not in rendered and "unrelated" not in rendered
    assert all(name.startswith(("get_", "describe_", "list_")) for name in calls)


def test_wrong_account_stops_before_reading_prod_resources():
    sdk, calls = session(account="111111111111")
    with pytest.raises(RuntimeError, match="Expected PROD account"):
        audit.collect(sdk, MID)
    assert calls == ["get_caller_identity"]


def test_one_failed_check_keeps_other_evidence_and_redacts_exception_body():
    sdk, _ = session(repository_error=True)
    result = audit.collect(sdk, MID)
    assert result["repositoryCollector"] == {"errorCode": "RuntimeError"}
    assert result["workspaceStorage"]["workspaces"][0]["objects"] == 2
    assert "private diagnostic text" not in json.dumps(result)


def test_log_scan_continues_empty_page_and_redacts_exception_message():
    from unittest.mock import Mock
    logs=Mock()
    logs.filter_log_events.side_effect=[{"events":[],"nextToken":"page-two"}, {"events":[
        {"timestamp":1,"message":'[ERROR] UndefinedTable: private table or SQL'},
        {"timestamp":2,"message":json.dumps(dict(status="failed",stage="db.transaction",errorType="UndefinedTable",sqlState="42P01",message="private sql",parameters="secret"))}]}]
    sdk=SimpleNamespace(client=lambda _:logs)
    result=audit.log_failures(sdk,"worker-group")
    assert logs.filter_log_events.call_args_list[1].kwargs["nextToken"] == "page-two"
    assert result["matchedEvents"] == 2 and result["truncated"] is False
    assert result["failures"][1]["failure"]["sqlState"] == "42P01"
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)
