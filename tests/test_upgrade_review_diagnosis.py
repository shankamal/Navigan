"""Read-only evidence must identify self-review without changing any grants."""
import json
from pathlib import Path
import runpy
from unittest.mock import MagicMock
import pytest

ROOT=Path(__file__).resolve().parents[1]
module=runpy.run_path(str(ROOT/"scripts/diagnose-upgrade-review-prod.py"))
ACTOR="4123ddfa-a0a1-7079-a3dd-58c0c633f678"
PLAN="UPG-314c1a2c855e447f8e7537304c39c351"


def session_fixture():
    session=MagicMock()
    clients={name:MagicMock() for name in ["sts","cloudformation","lambda","rds","rds-data","cognito-idp","iam"]}
    session.client.side_effect=lambda name:clients[name]
    clients["sts"].get_caller_identity.return_value={"Account":module["ACCOUNT"]}
    clients["cloudformation"].describe_stacks.return_value={"Stacks":[{"Parameters":[{"ParameterKey":"DatabaseName","ParameterValue":"navigan"},{"ParameterKey":"ApiDatabaseSecretArn","ParameterValue":"secret-arn"}]}]}
    clients["cloudformation"].describe_stack_resource.return_value={"StackResourceDetail":{"PhysicalResourceId":"resource"}}
    clients["lambda"].get_function_configuration.return_value={"Environment":{"Variables":{"IDENTITY_USER_POOL_ID":"pool"}},"Role":"arn:aws:iam::905418045935:role/lambda"}
    clients["rds"].describe_db_clusters.return_value={"DBClusters":[{"DBClusterArn":"cluster-arn"}]}
    clients["rds-data"].begin_transaction.return_value={"transactionId":"read-tx"}
    plan={"plan_id":PLAN,"customer_id":"CUS-one","created_by":ACTOR,"submitted_by":"21638d6a-7001-70d7-f897-5cbac88922b6","approved_by":None,"status":"SUBMITTED"}
    def query(**kwargs):
        return {"formattedRecords":json.dumps([plan] if "FROM cluster_management.upgrade_plans p" in kwargs["sql"] else [])}
    clients["rds-data"].execute_statement.side_effect=query
    clients["cognito-idp"].list_users.return_value={"Users":[{"Attributes":[{"Name":"sub","Value":ACTOR},{"Name":"email","Value":"reviewer@example.com"},{"Name":"name","Value":"Reviewer Name"}]}]}
    clients["iam"].simulate_principal_policy.return_value={"EvaluationResults":[{"EvalDecision":"allowed"}]}
    return session,clients


def test_reports_original_creator_even_after_another_user_resubmits_without_writes():
    session,clients=session_fixture()
    result=module["inspect_plan"](session,PLAN,"reviewer@example.com")
    assert result["readOnly"] is True
    assert result["reviewerMatchesCreator"] is True and result["reviewerMatchesSubmitter"] is False
    assert result["approvalFinding"]=="SELF_APPROVAL_BLOCKED"
    assert result["reviewerProfile"]["resolvedName"]=="Reviewer Name"
    api=clients["rds-data"]
    api.rollback_transaction.assert_called_once()
    api.commit_transaction.assert_not_called()
    assert all(c.kwargs["sql"].lstrip().startswith(("SELECT ","SET TRANSACTION READ ONLY")) for c in api.execute_statement.call_args_list)
    assert all(c.kwargs.get("Filter") and c.kwargs["Limit"]==2 for c in clients["cognito-idp"].list_users.call_args_list)
    for client in clients.values():
        assert not any(c[0].startswith(("update_","put_","admin_update_")) for c in client.method_calls)


def test_missing_profile_name_is_identified_without_guessing_from_email():
    directory=MagicMock()
    directory.list_users.return_value={"Users":[{"Attributes":[{"Name":"sub","Value":ACTOR},{"Name":"email","Value":"reviewer@example.com"}]}]}
    result=module["lookup"](directory,"pool","sub",ACTOR)
    assert result["profileNameMissing"] is True and result["resolvedName"] is None


def test_unexpected_account_stops_before_plan_or_directory_access():
    session,clients=session_fixture()
    clients["sts"].get_caller_identity.return_value={"Account":"000000000001"}
    with pytest.raises(ValueError,match="Unexpected AWS account"):
        module["inspect_plan"](session,PLAN,"reviewer@example.com")
    session.client.assert_called_once_with("sts")


def test_query_error_rolls_back_and_read_adapter_rejects_mutation():
    session,clients=session_fixture()
    clients["rds-data"].execute_statement.side_effect=RuntimeError("read failed")
    with pytest.raises(RuntimeError,match="read failed"):
        module["inspect_plan"](session,PLAN,"reviewer@example.com")
    clients["rds-data"].rollback_transaction.assert_called_once()
    with pytest.raises(ValueError,match="SELECT"):
        module["ReadOnlyDataAPI"](MagicMock(),{}).execute("UPDATE anything SET status='ACTIVE'")
