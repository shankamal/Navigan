import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('collector_parity',ROOT/'scripts/align-dev-collectors-with-prod.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


def service(task='old',rollout='COMPLETED'):
    return {'desiredCount':1,'runningCount':1,'pendingCount':0,'taskDefinition':task,
            'deployments':[{'rolloutState':rollout}]}


def test_registration_preserves_all_dev_settings_and_sidecars():
    task={'family':'dev-family','taskRoleArn':'dev-role','executionRoleArn':'dev-execution',
          'containerDefinitions':[{'name':'collector','image':'dev-old','environment':[{'name':'DB_NAME','value':'navigan_dev'}],
                                   'readonlyRootFilesystem':True,'mountPoints':[{'sourceVolume':'tmp','containerPath':'/tmp'}]},
                                  {'name':'sidecar','image':'sidecar-old'}],
          'volumes':[{'name':'tmp'}],'networkMode':'awsvpc','runtimePlatform':{'cpuArchitecture':'X86_64'},
          'revision':1,'taskDefinitionArn':'old','registeredAt':'timestamp'}
    original=copy.deepcopy(task)
    allowed=set(task)-{'revision','taskDefinitionArn','registeredAt'}
    tags=[{'key':'environment','value':'dev'}]
    result=release.registration(task,tags,'dev-new',allowed)
    assert task==original
    assert result['taskRoleArn']=='dev-role'
    assert result['executionRoleArn']=='dev-execution'
    assert result['containerDefinitions'][0]['environment'][0]['value']=='navigan_dev'
    assert result['containerDefinitions'][0]['image']=='dev-new'
    assert result['containerDefinitions'][1]==original['containerDefinitions'][1]
    assert result['volumes']==original['volumes']
    assert result['tags']==tags
    assert not set(result)&{'revision','taskDefinitionArn','registeredAt'}


@pytest.mark.parametrize('containers',[[],[{'name':'collector','image':'one'},{'name':'collector','image':'two'}]])
def test_registration_rejects_missing_or_duplicate_collector(containers):
    with pytest.raises(RuntimeError,match='Unexpected collector task'):
        release.registration({'containerDefinitions':containers},[],'new',{'containerDefinitions'})


def test_manifest_accepts_only_identical_duplicate_rows():
    value={'config':{'digest':'config'},'layers':[{'digest':'layer'}]}
    row={'imageId':{'imageDigest':'sha256:expected'},'imageManifest':json.dumps(value),
         'imageManifestMediaType':'application/vnd.oci.image.manifest.v1+json'}
    response={'images':[row,copy.deepcopy(row)]}
    ecr=SimpleNamespace(batch_get_image=lambda **kw:response)
    assert release.manifest(ecr,'repo','sha256:expected')==value
    response['images'][1]['imageManifest']='{}'
    with pytest.raises(RuntimeError,match='Conflicting'):
        release.manifest(ecr,'repo','sha256:expected')


def test_content_identity_requires_exact_config_and_ordered_layers():
    a={'config':{'digest':'config'},'layers':[{'digest':'a'},{'digest':'b'}]}
    b={'config':{'digest':'config'},'layers':[{'digest':'b'},{'digest':'a'}]}
    assert release.content_identity(a)!=release.content_identity(b)


def test_stable_does_not_accept_early_service_waiter_state():
    assert release.stable(service())
    assert not release.stable(service(rollout='IN_PROGRESS'))
    current=service();current['deployments'].append({'rolloutState':'COMPLETED'})
    assert not release.stable(current)


def test_wait_rejects_completed_rollback():
    ecs=SimpleNamespace(describe_services=lambda **kw:{'services':[service(task='rollback')]})
    with pytest.raises(RuntimeError,match='rolled back'):
        release.wait_service(ecs,'cluster','service','candidate')


def test_wait_accepts_only_completed_requested_task(monkeypatch):
    values=iter([service(task='candidate',rollout='IN_PROGRESS'),service(task='candidate')])
    ecs=SimpleNamespace(describe_services=lambda **kw:{'services':[next(values)]})
    monkeypatch.setattr(release.time,'sleep',lambda seconds:None)
    release.wait_service(ecs,'cluster','service','candidate')


def test_invalid_plan_rejected_before_any_aws_call(tmp_path):
    plan=tmp_path/'release-plan.json';plan.write_text(json.dumps({'format':'prod-plan'}))
    with pytest.raises(RuntimeError,match='Invalid DEV collector plan'):
        release.execute(object(),plan)


def test_revision_or_configuration_changes_stop_promotion(tmp_path,monkeypatch):
    plan=tmp_path/'release-plan.json'
    plan.write_text(json.dumps({'format':release.FORMAT,'account':release.ACCOUNT,'region':release.REGION,
                               'dev':{'expected':'old'},'prod':{'expected':'old'}}))
    monkeypatch.setattr(release,'snapshot',lambda session,label:{'changed':True})
    monkeypatch.setattr(release,'signature',lambda value:value)
    with pytest.raises(RuntimeError,match='changed since preparation'):
        release.execute(object(),plan)


def test_execute_promotes_only_dev_targets_and_retains_dev_configuration(tmp_path,monkeypatch):
    original,raw=b'dev-zip',b'prod-zip'
    def value(label,payload):
        parent=release.PARENTS[label]
        return {'worker':{'Configuration':{'FunctionName':parent+'-workspace-repositories',
                    'RevisionId':label+'-revision','CodeSha256':release.support.zip_sha(payload),
                    'Environment':{'Variables':{'DB_NAME':release.support.DATABASES[label]}}}},
                'service':{'serviceArn':label+'-service','serviceName':label+'-service','desiredCount':1},
                'task':{'taskDefinitionArn':label+'-task','family':parent+'-workspace-images-WorkerTask-family',
                        'taskRoleArn':label+'-role','containerDefinitions':[{'name':'collector','image':label+'-old',
                        'environment':[{'name':'DB_NAME','value':release.support.DATABASES[label]}]}]},
                'tags':[],'cluster':label+'-cluster','image':label+'-image'}
    dev,prod=value('dev',original),value('prod',raw)
    path=tmp_path/'plan.json'
    path.write_text(json.dumps({'format':release.FORMAT,'account':release.ACCOUNT,'region':release.REGION,
                               'dev':release.signature(dev),'prod':release.signature(prod)}))
    (tmp_path/'dev-repository-original.zip').write_bytes(original)
    (tmp_path/'prod-repository.zip').write_bytes(raw)
    monkeypatch.setattr(release,'snapshot',lambda session,label:copy.deepcopy(dev if label=='dev' else prod))
    monkeypatch.setattr(release,'copy_image',lambda session,source,directory:'dev-repository@sha256:copied')
    monkeypatch.setattr(release,'wait_service',lambda ecs,cluster,service,task:None)
    writes=[]
    class Lambda:
        def update_function_code(self,**kwargs):writes.append(('lambda',kwargs))
        def get_waiter(self,name):return SimpleNamespace(wait=lambda **kw:None)
        def get_function_configuration(self,**kwargs):
            cfg=copy.deepcopy(dev['worker']['Configuration']);cfg['CodeSha256']=release.support.zip_sha(raw)
            return cfg
    class ECS:
        meta=SimpleNamespace(service_model=SimpleNamespace(operation_model=lambda name:SimpleNamespace(
            input_shape=SimpleNamespace(members={'family':None,'taskRoleArn':None,'containerDefinitions':None}))))
        def register_task_definition(self,**kwargs):
            writes.append(('register',kwargs));return {'taskDefinition':{'taskDefinitionArn':'dev-candidate'}}
        def update_service(self,**kwargs):writes.append(('service',kwargs))
        def list_tasks(self,**kwargs):return {'taskArns':['dev-running']}
        def describe_tasks(self,**kwargs):return {'tasks':[{'taskDefinitionArn':'dev-candidate',
            'containers':[{'name':'collector','imageDigest':'sha256:copied'}]}]}
    session=SimpleNamespace(client=lambda name:Lambda() if name=='lambda' else ECS())
    release.execute(session,path)
    assert [kind for kind,_ in writes]==['register','lambda','service']
    assert writes[0][1]['taskRoleArn']=='dev-role'
    assert writes[0][1]['containerDefinitions'][0]['environment'][0]['value']=='navigan_dev'
    assert writes[1][1]['FunctionName']==release.PARENTS['dev']+'-workspace-repositories'
    assert writes[1][1]['ZipFile']==raw
    assert writes[2][1]=={'cluster':'dev-cluster','service':'dev-service','taskDefinition':'dev-candidate'}
