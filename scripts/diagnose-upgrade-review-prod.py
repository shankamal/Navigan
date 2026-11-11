#!/usr/bin/env python3
"""Read-only diagnosis of one PROD upgrade plan and its named reviewer.

No grants, users, plans, schedules or cloud resources are changed. No bearer
JWT, secret value or full directory is read or printed.
"""
import argparse
import json
from pathlib import Path
import re
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from navigan.shared.access import AccessRepository, AccessEvaluator
from navigan.shared.auth import Principal
from navigan.modules.cluster_management.upgrade_actors import real_name

ACCOUNT, REGION, STACK = "905418045935", "ap-south-1", "navigan-custmanagement-cfnstk"
PLAN = re.compile(r"UPG-[a-f0-9]{32}")
SUB = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def error_code(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)


class ReadOnlyDataAPI:
    def __init__(self, client, request):
        self.client, self.request = client, request

    def execute(self, sql, params=()):
        if not sql.lstrip().upper().startswith("SELECT "):
            raise ValueError("Diagnosis permits SELECT statements only")
        parameters = []
        for i, value in enumerate(params):
            sql = sql.replace("%s", ":p" + str(i), 1)
            parameters.append({"name": "p" + str(i), "value": {"stringValue": str(value)}})
        result = self.client.execute_statement(**self.request, sql=sql,
                                               parameters=parameters, formatRecordsAs="JSON")
        rows = json.loads(result.get("formattedRecords", "[]"))
        class Cursor:
            def fetchall(self): return rows
            def fetchone(self): return rows[0] if rows else None
        return Cursor()


def lookup(directory, pool, attribute, value):
    if not pool:
        return {"lookupStatus": "POOL_NOT_CONFIGURED"}
    if attribute == "sub" and not SUB.fullmatch(value or ""):
        return {"lookupStatus": "UNRECOGNISED_SUBJECT"}
    if any(c in value for c in ['"', "\\", "\n", "\r"]):
        raise ValueError("Invalid identity filter")
    try:
        page = directory.list_users(UserPoolId=pool, Filter=f'{attribute} = "{value}"', Limit=2)
        matches = []
        for user in page.get("Users", []):
            attrs = {a["Name"]: a["Value"] for a in user.get("Attributes", [])}
            if str(attrs.get(attribute, "")).casefold() == value.casefold():
                matches.append(attrs)
        if len(matches) != 1:
            return {"lookupStatus": "NOT_FOUND" if not matches else "AMBIGUOUS"}
        attrs = matches[0]
        actor = attrs.get("sub", "")
        full = " ".join(attrs.get(k, "") for k in ("given_name", "family_name")).strip()
        name = real_name(attrs.get("name"), actor) or real_name(full, actor)
        return {"lookupStatus": "FOUND", "userId": actor,
                "name": attrs.get("name"), "givenName": attrs.get("given_name"),
                "familyName": attrs.get("family_name"), "email": attrs.get("email"),
                "resolvedName": name, "profileNameMissing": not bool(name)}
    except (ClientError, BotoCoreError) as error:
        return {"lookupStatus": "LOOKUP_FAILED", "errorCode": error_code(error)}


def inspect_plan(session, plan_id, reviewer_email):
    if not PLAN.fullmatch(plan_id):
        raise ValueError("Use the full UPG plan ID")
    if session.client("sts").get_caller_identity()["Account"] != ACCOUNT:
        raise ValueError("Unexpected AWS account; stopped before reading plan data")
    cfn = session.client("cloudformation")
    parent = cfn.describe_stacks(StackName=STACK)["Stacks"][0]
    params = {p["ParameterKey"]: p["ParameterValue"] for p in parent["Parameters"]}
    if params.get("DatabaseName") != "navigan":
        raise ValueError("Expected PROD database navigan")
    child = cfn.describe_stack_resource(StackName=STACK, LogicalResourceId="ClusterManagement")["StackResourceDetail"]["PhysicalResourceId"]
    function = cfn.describe_stack_resource(StackName=child, LogicalResourceId="ClusterFunction")["StackResourceDetail"]["PhysicalResourceId"]
    config = session.client("lambda").get_function_configuration(FunctionName=function)
    pool = config.get("Environment", {}).get("Variables", {}).get("IDENTITY_USER_POOL_ID")
    directory_pool = pool or params.get("IdentityUserPoolId")
    rds = session.client("rds").describe_db_clusters(DBClusterIdentifier="aws-infra-platform-db")["DBClusters"][0]
    api = session.client("rds-data")
    base = {"resourceArn": rds["DBClusterArn"], "secretArn": params["ApiDatabaseSecretArn"], "database": "navigan"}
    tx = api.begin_transaction(**base)["transactionId"]
    request = {**base, "transactionId": tx}
    try:
        api.execute_statement(**request, sql="SET TRANSACTION READ ONLY")
        db = ReadOnlyDataAPI(api, request)
        row = db.execute("SELECT p.plan_id,p.cluster_id,p.customer_id,p.status,p.scheduled_for,"
            "p.created_by,p.submitted_by,p.approved_by,"
            "creator.display_name AS created_by_name,submitter.display_name AS submitted_by_name,"
            "(p.plan_spec <> '{}'::jsonb) AS has_component_scope "
            "FROM cluster_management.upgrade_plans p "
            "LEFT JOIN access_management.users creator ON creator.user_id=p.created_by "
            "LEFT JOIN access_management.users submitter ON submitter.user_id=p.submitted_by "
            "WHERE p.plan_id=%s", [plan_id]).fetchone()
        if not row:
            raise ValueError("Plan not found in the confirmed PROD database")
        directory = session.client("cognito-idp")
        actors = {value for key in ("created_by", "submitted_by", "approved_by") if (value := row.get(key))}
        profiles = {actor: lookup(directory, directory_pool, "sub", actor) for actor in sorted(actors)}
        reviewer = lookup(directory, directory_pool, "email", reviewer_email)
        reviewer_id = reviewer.get("userId")
        result = {"readOnly": True, "plan": row, "lambdaIdentityPoolConfigured": bool(pool),
                  "actorProfiles": profiles, "reviewerProfile": reviewer}
        if reviewer_id:
            source = AccessRepository(db)
            user = source.user(reviewer_id)
            result["reviewerMatchesCreator"] = reviewer_id == row.get("created_by")
            result["reviewerMatchesSubmitter"] = reviewer_id == row.get("submitted_by")
            result["authorizationSource"] = "DYNAMIC" if user else "LEGACY_CLAIMS"
            if user:
                # Dynamic approval privileges do not depend on legacy role-name inference.
                access = AccessEvaluator(source).evaluate(Principal(reviewer_id, frozenset(), frozenset()))
                result["databaseDisplayName"] = access.display_name
                result["databaseApprovalPrivilege"] = access.has("cluster.approve") or access.has("cluster.upgrade.approve")
                result["databaseCustomerScope"] = access.can_access_customer(row["customer_id"])
            if result["reviewerMatchesCreator"] or result["reviewerMatchesSubmitter"]:
                result["approvalFinding"] = "SELF_APPROVAL_BLOCKED"
            elif user and not result["databaseApprovalPrivilege"]:
                result["approvalFinding"] = "DATABASE_APPROVAL_PRIVILEGE_MISSING"
            else:
                result["approvalFinding"] = "VERIFY_CURRENT_ACCESS_ME_PRIVILEGES_AND_SCOPE"
        else:
            result["approvalFinding"] = "REVIEWER_PROFILE_NOT_RESOLVED"
        try:
            policy = session.client("iam").simulate_principal_policy(PolicySourceArn=config["Role"],
                ActionNames=["cognito-idp:ListUsers"],
                ResourceArns=[f"arn:aws:cognito-idp:{REGION}:{ACCOUNT}:userpool/{directory_pool}"])
            result["lambdaDirectoryPolicySimulation"] = [p["EvalDecision"] for p in policy["EvaluationResults"]]
        except (ClientError, BotoCoreError) as error:
            result["lambdaDirectoryPolicySimulation"] = error_code(error)
        return result
    finally:
        api.rollback_transaction(resourceArn=base["resourceArn"], secretArn=base["secretArn"], transactionId=tx)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--reviewer-email", required=True)
    args = parser.parse_args()
    result = inspect_plan(boto3.Session(profile_name=args.profile, region_name=REGION), args.plan_id, args.reviewer_email)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
