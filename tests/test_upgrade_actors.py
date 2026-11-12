from unittest.mock import MagicMock
from botocore.exceptions import ClientError
from navigan.modules.cluster_management.upgrade_actors import UpgradeActorNames
from navigan.modules.cluster_management.upgrade_plans import EksUpgradePlans

ACTOR = "21638d6a-7001-70d7-f897-5cbac88922b6"
OTHER = "4123ddfa-a0a1-7079-a3dd-58c0c633f678"


def directory(*attributes):
    client=MagicMock()
    client.list_users.return_value={"Users":[{"Attributes":[{"Name":"sub","Value":ACTOR},*[{"Name":name,"Value":value} for name,value in attributes]]}]}
    return client


def test_database_name_is_preferred_without_a_directory_scan():
    client=directory(("name","Directory Person"))
    names=UpgradeActorNames(client,"pool")
    assert names.resolve(ACTOR,"Suhas Yadav")=="Suhas Yadav"
    client.list_users.assert_not_called()


def test_legacy_subject_resolves_real_name_using_exact_sub_and_request_cache():
    client=directory(("name","Suhas Yadav"))
    names=UpgradeActorNames(client,"pool")
    assert names.resolve(ACTOR,ACTOR)=="Suhas Yadav"
    assert names.resolve(ACTOR)=="Suhas Yadav"
    client.list_users.assert_called_once_with(UserPoolId="pool",Filter=f'sub = "{ACTOR}"',Limit=2)


def test_given_and_family_names_are_used_when_name_attribute_is_missing():
    client=directory(("given_name","Suhas"),("family_name","Yadav"))
    assert UpgradeActorNames(client,"pool").resolve(ACTOR)=="Suhas Yadav"


def test_no_name_is_invented_from_email_uuid_or_other_user_profile():
    client=directory(("name",ACTOR),("email","someone@example.com"))
    names=UpgradeActorNames(client,"pool")
    assert names.resolve(ACTOR)=="Name unavailable"
    assert names.resolve(OTHER)=="Name unavailable"
    assert names.resolve('bad" OR sub = "other')=="Name unavailable"
    assert names.resolve(None) is None
    assert client.list_users.call_count==2


def test_directory_failure_does_not_break_plan_reads_or_broaden_authorization():
    client=directory()
    client.list_users.side_effect=ClientError({"Error":{"Code":"AccessDeniedException"}},"ListUsers")
    names=UpgradeActorNames(client,"pool")
    assert names.resolve(ACTOR)=="Name unavailable"
    assert names.resolve(OTHER)=="Name unavailable"
    client.list_users.assert_called_once()


def test_plan_presentation_keeps_audit_ids_and_uses_profile_names():
    service=EksUpgradePlans(MagicMock(),MagicMock(user_id=ACTOR,display_name=ACTOR),"test",MagicMock())
    service._actor_names=UpgradeActorNames(directory(("name","Suhas Yadav")),"pool")
    plan=service.present({"created_by":ACTOR,"submitted_by":ACTOR,"approved_by":None})
    assert plan["createdBy"]==plan["submittedBy"]==ACTOR
    assert plan["createdByName"]==plan["submittedByName"]=="Suhas Yadav"
    assert plan["approvedByName"] is None


def test_detail_query_loads_names_and_locks_only_the_plan_after_scope_check():
    repo=MagicMock();repo.db.execute.return_value.fetchone.return_value={"plan_id":"UPG-one"}
    service=EksUpgradePlans(repo,MagicMock(),"test",MagicMock())
    service.get("CLU-one","UPG-one",lock=True)
    repo.get.assert_called_once_with("CLU-one")
    sql,args=repo.db.execute.call_args.args
    assert "LEFT JOIN access_management.users creator" in sql
    assert sql.endswith("FOR UPDATE OF p")
    assert args==["CLU-one","UPG-one"]
