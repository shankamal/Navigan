from datetime import timedelta
from unittest.mock import MagicMock
import pytest
from navigan.modules.cluster_management.utility_upgrades import UtilityUpgradePlans, CreateUtilityUpgradePlan, upstream_releases
from navigan.modules.cluster_management.upgrade_plans import EksUpgradePlans, utcnow
from navigan.shared.access import EffectiveAccess, Scope
from navigan.shared.errors import ApiError


def access(user='architect',privileges=('cluster.upgrade.plan',)):
    return EffectiveAccess(user,user,1,frozenset(privileges),(Scope('PLATFORM'),))


def service(code='headlamp',status='READY',version='0.45.0',age=0):
    repo=MagicMock()
    repo.get.return_value={'cluster_id':'CLU-live','customer_id':'CUS-live'}
    repo.platform_components.return_value={'components':[{'componentCode':code,'status':status,'version':version,'syncStatus':'Synced','observedAt':(utcnow()-timedelta(seconds=age)).isoformat()}]}
    repo.db.execute.return_value.fetchone.return_value=None
    plans=UtilityUpgradePlans(repo,access(),'test',releases=lambda _:['0.46.0','0.45.0'])
    return plans,repo


def test_catalog_uses_fixed_upstream_and_only_stable_newer_chart_releases():
    urls=[]
    def fetch(url):
        urls.append(url)
        return [{'tag_name':'headlamp-helm-0.46.0'}, {'tag_name':'v0.47.0'},
                {'tag_name':'headlamp-helm-0.47.0','prerelease':True}, {'tag_name':'headlamp-helm-0.44.0'}]
    assert upstream_releases('headlamp',fetch)==['0.46.0','0.44.0']
    assert urls==['https://api.github.com/repos/kubernetes-sigs/headlamp/releases?per_page=100']
    plans,_=service()
    assert plans.options('CLU-live','headlamp')['versions']==['0.46.0']


def test_missing_adapter_version_stale_and_progressing_evidence_are_explained():
    for kwargs,phrase in [({'version':None},'installed chart version'),({'status':'PROGRESSING'},'PROGRESSING'),({'age':901},'15 minutes')]:
        plans,_=service(**kwargs)
        assert phrase in plans.options('CLU-live','headlamp')['blockReason']
    plans,_=service()
    assert 'adapter' in plans.options('CLU-live','argocd')['blockReason']


def test_create_utility_draft_is_persisted_audited_and_does_not_execute():
    plans,repo=service()
    result=plans.create('CLU-live',{'utilityCode':'headlamp','targetVersion':'0.46.0','changeReason':'Upgrade dashboard chart'})
    assert result['kind']=='UTILITY' and result['status']=='DRAFT'
    assert result['utilityEvidence']['chart']=='headlamp'
    assert 'readinessEvidence' not in result
    repo.system_repository_access.assert_called_once_with('CLU-live')
    assert any('INSERT INTO cluster_management.utility_upgrade_plans' in c.args[0] for c in repo.db.execute.call_args_list)
    assert any('cluster_audit_log' in c.args[0] for c in repo.db.execute.call_args_list)
    assert all('upgrade_plans ' not in c.args[0] or 'utility_upgrade_plans' in c.args[0] for c in repo.db.execute.call_args_list)


def test_missing_planning_permission_and_unverified_target_are_blocked():
    plans,repo=service();plans.access=access('suhas',('cluster.upgrade.approve',))
    with pytest.raises(ApiError) as error:
        plans.create('CLU-live',{'utilityCode':'headlamp','targetVersion':'0.46.0','changeReason':'Upgrade chart'})
    assert error.value.status==403
    plans.access=access()
    with pytest.raises(ApiError) as error:
        plans.create('CLU-live',{'utilityCode':'headlamp','targetVersion':'99.99.99','changeReason':'Upgrade chart'})
    assert error.value.code=='UTILITY_TARGET_UNAVAILABLE'


def test_monitoring_apps_share_one_plan_group_and_active_plan_is_blocked():
    plans,repo=service('grafana',version='89.2.4');plans.releases=lambda _:['90.0.0']
    repo.platform_components.return_value['components'].append({**repo.platform_components.return_value['components'][0],'componentCode':'prometheus'})
    repo.db.execute.return_value.fetchone.return_value={'plan_id':'UPG-active'}
    with pytest.raises(ApiError) as error:
        plans.create('CLU-live',{'utilityCode':'grafana','targetVersion':'90.0.0','changeReason':'Upgrade monitoring'})
    assert error.value.code=='ACTIVE_UTILITY_PLAN_EXISTS'
    assert repo.db.execute.call_args.args[1][1]=='kube-prometheus-stack'


def test_utility_cannot_enter_eks_execution_even_when_approved():
    plans,repo=service();plans.get=MagicMock(return_value={'status':'SCHEDULED'})
    for action in ['execute','refresh']:
        with pytest.raises(ApiError) as error:plans.change('CLU-live','UPG-plan',action,{'version':1})
        assert error.value.code=='UTILITY_EXECUTION_NOT_ENABLED'
    repo.db.execute.assert_not_called()


def test_narrow_upgrade_reviewer_can_approve_but_creator_cannot():
    for user,creator,allowed in [('suhas','architect',True),('architect','architect',False)]:
        plans,_=service();plans.access=access(user,('cluster.upgrade.approve',))
        plans.get=MagicMock(return_value={'version':1,'created_by':creator,'status':'SUBMITTED','scheduled_for':utcnow()+timedelta(days=1)})
        plans._transition=MagicMock(return_value={'status':'SCHEDULED'})
        if allowed:assert plans.change('CLU-live','UPG-plan','approve',{'version':1})['status']=='SCHEDULED'
        else:
            with pytest.raises(ApiError) as error:plans.change('CLU-live','UPG-plan','approve',{'version':1})
            assert error.value.code=='MAKER_CHECKER_REQUIRED'
        assert not plans.access.has('cluster.approve')


def test_utility_schedule_requires_timezone():
    with pytest.raises(ValueError,match='timezone'):
        CreateUtilityUpgradePlan(utilityCode='headlamp',targetVersion='0.46.0',changeReason='Upgrade chart',scheduledFor='2027-01-01T12:00:00')


def test_engineer_plans_but_cannot_approve_and_architect_reviews_without_provisioning():
    plans,repo=service()
    engineer=access('suhas',('cluster.upgrade.plan',))
    plans.access=engineer
    result=plans.create('CLU-live',{'utilityCode':'headlamp','targetVersion':'0.46.0','changeReason':'Upgrade dashboard chart'})
    assert result['createdBy']=='suhas'
    plans.get=MagicMock(return_value={'version':1,'created_by':'other-maker','submitted_by':'other-maker','status':'SUBMITTED'})
    with pytest.raises(ApiError) as error:plans.change('CLU-live','UPG-test','approve',{'version':1})
    assert error.value.status==403
    plans.access=access('architect',('cluster.upgrade.approve',))
    with pytest.raises(ApiError) as error:plans.create('CLU-live',{'utilityCode':'headlamp','targetVersion':'0.46.0','changeReason':'Upgrade chart'})
    assert error.value.status==403
    assert not engineer.has('cluster.plan') and not engineer.has('cluster.apply')


def test_role_migration_changes_only_upgrade_grants_and_preserves_custom_denies():
    from pathlib import Path
    source=(Path(__file__).parents[1]/'database/migrations/032_upgrade_maker_reviewer_roles.sql').read_text()
    assert "'cluster.upgrade.plan'" in source
    assert "r.role_code='CLOUD_ENGINEER'" in source
    assert "rp.effect='ALLOW' AND rp.created_by='SYSTEM'" in source
    assert "r.role_type='SYSTEM_TEMPLATE'" in source
    assert "'cluster.plan'" not in source
