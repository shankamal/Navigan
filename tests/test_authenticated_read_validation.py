import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('auth_read_test',ROOT/'scripts/validate-authenticated-read-paths.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)


class Response:
    status=200
    def __init__(self,value):self.value=value
    def __enter__(self):return self
    def __exit__(self,*args):return None
    def read(self,limit):return json.dumps(self.value).encode()


def test_only_get_requests_and_no_token_in_report():
    seen=[]
    def open_request(request,timeout):
        seen.append((request,timeout));return Response({'items':[]})
    result=helper.check('dev','https://example.execute-api.test','private-token',helper.paths('migration/one','cluster/one'),9,open_request)
    assert result['passed'] and len(result['requests'])==11
    assert all(request.method=='GET' and request.full_url.startswith('https://example.execute-api.test/') for request,_ in seen)
    assert all('%2F' in request.full_url for request,_ in seen[-6:])
    assert 'private-token' not in json.dumps(result)


@pytest.mark.parametrize('value',['http://example.test','https://user:secret@example.test','https://example.test/path',
                                  'https://example.test?token=private'])
def test_rejects_unsafe_origins(value):
    with pytest.raises(RuntimeError):helper.origin(value)


def test_non_json_or_non_200_fails_without_printing_body():
    class Bad(Response):
        status=201
    result=helper.check('prod','https://example.test','token',['/read'],opener=lambda *a,**k:Bad({'private':'value'}))
    assert not result['passed'] and 'private' not in json.dumps(result)


def test_base_validation_has_summary_and_workflow_list_reads():
    assert helper.paths()==['/api/v1/customers/summary','/api/v1/environments/summary',
        '/api/v1/clusters/summary','/api/v1/migrations','/api/v1/source-clusters']
