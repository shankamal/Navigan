"""Keep the deployed API surface and authentication aligned with the published contract."""

import json
from pathlib import Path
import yaml


class CloudFormationLoader(yaml.SafeLoader):
    pass


def intrinsic(loader, tag, node):
    return {tag: loader.construct_scalar(node)}


CloudFormationLoader.add_multi_constructor("!", intrinsic)


def test_gateway_exposes_every_documented_operation_with_authentication():
    root = Path(__file__).resolve().parents[1]
    template = yaml.load((root / "infrastructure/template.yaml").read_text(), Loader=CloudFormationLoader)
    contract = json.loads((root / "docs/openapi.json").read_text())
    expected = {(method.upper(), path) for path, methods in contract["paths"].items() for method in methods}
    events = template["Resources"]["CustomerFunction"]["Properties"]["Events"]
    actual = {(event["Properties"]["Method"], event["Properties"]["Path"]) for event in events.values()}
    assert actual == expected
    assert len(events) == len(expected) == 18
    for event in events.values():
        props = event["Properties"]
        assert event["Type"] == "HttpApi"
        assert props["ApiId"] == {"Ref": "Api"}
        assert props["PayloadFormatVersion"] == "2.0"
        assert props["TimeoutInMillis"] == 29000
        assert props["Auth"] == {"Authorizer": "EnterpriseJwt", "AuthorizationScopes": [{"Ref": "JwtScope"}]}
    assert template["Resources"]["Api"]["Properties"]["Auth"]["DefaultAuthorizer"] == "EnterpriseJwt"
