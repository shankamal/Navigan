import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from jsonschema import Draft202012Validator
from navigan.shared.auth import Principal
from navigan.shared.errors import ApiError
from navigan.modules.environment_management.configuration import schema, validate
from navigan.modules.environment_management.handler import resource_path, query_params, lambda_handler
from navigan.modules.environment_management.service import Service, TRANSITIONS
from navigan.modules.environment_management.models import AwsDiscoveryRequest
from navigan.modules.environment_management.discovery import _route_profile, _subnet_routes


def example(distribution):
    def fill(node):
        if "const" in node:
            return node["const"]
        if "enum" in node:
            return node["enum"][0]
        if node["type"] == "object":
            return {k: fill(v) for k, v in node["properties"].items() if k in node.get("required", [])}
        if node["type"] == "array":
            return [fill(node["items"]) for _ in range(node.get("minItems", 1))]
        pattern = node.get("pattern", "")
        mappings = {
            "Account ID": "123456789012",
            "Tenant ID": "11111111-1111-1111-1111-111111111111",
            "Subscription ID": "11111111-1111-1111-1111-111111111111",
            "Project ID": "navigan-test",
            "Network resource name": "projects/navigan-test/global/networks/main",
            "Subnetwork resource name": "projects/navigan-test/regions/us-central1/subnetworks/main",
            "Node service account": "nodes@navigan-test.iam.gserviceaccount.com",
            "VPC ID": "vpc-123abc",
            "Subnet ID": "subnet-123abc",
            "Security group ID": "sg-123abc",
            "Role ARN": "arn:aws:iam::123456789012:role/example",
            "KMS key ARN": "arn:aws:kms:ap-south-1:123456789012:key/abc",
        }
        if node.get("title") in mappings:
            return mappings[node["title"]]
        if pattern.startswith("^/subscriptions"):
            return "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/demo/providers/Microsoft.Network/example/main"
        if pattern.startswith("^ocid1"):
            return "ocid1." + pattern.split("\\.")[1] + ".oc1..example"
        return "example"

    config = fill(schema(distribution, "1.0"))
    if distribution == "EKS":
        config["location"]["region"] = "ap-south-1"
        for key in ["clusterSubnets", "nodeSubnets"]:
            config["network"][key] = [
                {"subnetId": "subnet-123abc", "availabilityZone": "ap-south-1a"},
                {"subnetId": "subnet-456def", "availabilityZone": "ap-south-1b"},
            ]
    return config


@pytest.mark.parametrize("dist", ["EKS", "AKS", "GKE", "OKE"])
def test_valid_provider_configuration_and_drafts(dist):
    Draft202012Validator.check_schema(schema(dist, "1.0"))
    validate({}, dist, "1.0")
    validate(example(dist), dist, "1.0", True)
    with pytest.raises(ApiError):
        validate({}, dist, "1.0", True)


@pytest.mark.parametrize(
    "config",
    [
        {"extensions": {"password": "hidden"}},
        {"extensions": {"nested": [{"private_key": "hidden"}]}},
        {"proxy": {"url": "https://user:password@host"}},
    ],
)
def test_secrets_rejected_in_drafts(config):
    with pytest.raises(ApiError) as error:
        validate(config, "EKS", "1.0")
    assert "hidden" not in str(error.value)


@pytest.mark.parametrize(
    "dist,key", [("AKS", "diskEncryptionSetResourceId"), ("GKE", "kmsKeyResourceName"), ("OKE", "kmsKeyOcid")]
)
def test_customer_managed_encryption_requires_reference(dist, key):
    config = example(dist)
    config["encryption"]["mode"] = "CUSTOMER_MANAGED"
    with pytest.raises(ApiError):
        validate(config, dist, "1.0", True)


def test_eks_az_rule_and_distribution_schema():
    config = example("EKS")
    config["network"]["nodeSubnets"][1]["availabilityZone"] = "ap-south-1a"
    with pytest.raises(ApiError):
        validate(config, "EKS", "1.0", True)
    with pytest.raises(ApiError):
        validate(example("GKE"), "AKS", "1.0", True)
    with pytest.raises(ApiError):
        schema("../../etc", "1.0")


def test_eks_rejects_cross_vpc_account_and_region_references():
    config = example("EKS")
    config["network"]["clusterSubnets"][0]["vpcId"] = "vpc-other"
    config["security"]["clusterSecurityGroups"][0]["vpcId"] = "vpc-other"
    config["iam"]["clusterRole"]["roleArn"] = "arn:aws:iam::210987654321:role/cluster"
    config["encryption"]["nodeVolumeKmsKey"]["keyArn"] = "arn:aws:kms:us-east-1:123456789012:key/abc"
    with pytest.raises(ApiError) as error:
        validate(config, "EKS", "1.0", True)
    fields = {item["field"] for item in error.value.details["fields"]}
    assert "configuration.network.clusterSubnets" in fields
    assert "configuration.security.clusterSecurityGroups" in fields
    assert "configuration.iam.clusterRole.roleArn" in fields
    assert "configuration.encryption.nodeVolumeKmsKey.keyArn" in fields


def test_route_table_classification_uses_effective_default_route():
    tables = [
        {
            "RouteTableId": "rtb-main",
            "VpcId": "vpc-1",
            "Associations": [{"Main": True}],
            "Routes": [{"DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": "nat-1"}],
        },
        {
            "RouteTableId": "rtb-public",
            "VpcId": "vpc-1",
            "Associations": [{"SubnetId": "subnet-public"}],
            "Routes": [{"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-1"}],
        },
    ]
    explicit, main = _subnet_routes(tables)
    assert _route_profile(main["vpc-1"]) == ("PRIVATE", "nat-1")
    assert _route_profile(explicit["subnet-public"]) == ("PUBLIC", "igw-1")


@pytest.mark.parametrize(
    "stage,path,expected",
    [
        ("v1", "/v1/api/v1/environments", "/api/v1/environments"),
        ("$default", "/api/v1/environments", "/api/v1/environments"),
        ("v1", "/v1/unrelated", "/v1/unrelated"),
    ],
)
def test_stage_normalization(stage, path, expected):
    assert resource_path({"rawPath": path, "requestContext": {"stage": stage}}) == expected


@pytest.mark.parametrize(
    "query",
    [
        {"sort": "name;drop table,asc"},
        {"page": "-1"},
        {"pageSize": "101"},
        {"createdFrom": "yesterday"},
        {"invalid": "x"},
    ],
)
def test_invalid_query(query):
    with pytest.raises(ApiError):
        query_params(query)


@pytest.mark.parametrize("action", list(TRANSITIONS))
def test_role_and_state_enforced(action):
    repo = MagicMock()
    repo.principal = Principal("test", frozenset({"SERVICE"}), frozenset())
    repo.get.return_value = {"version": 1, "status": "DRAFT"}
    with pytest.raises(ApiError) as error:
        Service(repo, "test").change("ENV-test", action, {"version": 1})
    assert error.value.status == 403
    repo.save.assert_not_called()


def test_stale_version_not_saved():
    repo = MagicMock()
    repo.get.return_value = {"version": 2}
    with pytest.raises(ApiError) as error:
        Service(repo, "test").change("ENV-test", "update", {"version": 1})
    assert error.value.code == "CONCURRENT_UPDATE"
    repo.save.assert_not_called()


def test_aws_discovery_request_requires_matching_fixed_role_and_distinct_regions():
    valid = {
        "customerId": "CUS-test",
        "accountId": "123456789012",
        "roleArn": "arn:aws:iam::123456789012:role/NaviganDiscoveryRole",
        "externalId": "navigan-test-123",
        "regions": ["ap-south-1"],
    }
    assert AwsDiscoveryRequest.model_validate(valid).accountId == "123456789012"
    with pytest.raises(Exception):
        AwsDiscoveryRequest.model_validate({**valid, "accountId": "210987654321"})
    with pytest.raises(Exception):
        AwsDiscoveryRequest.model_validate({**valid, "regions": ["ap-south-1", "ap-south-1"]})


def test_environment_review_must_be_independent():
    repo = MagicMock()
    repo.principal = Principal("maker", frozenset({"PLATFORM_ARCHITECT"}), frozenset(), True)
    repo.get.return_value = {
        "version": 1,
        "status": "SUBMITTED",
        "created_by": "maker",
        "workflow": {"submitted": {"by": "maker"}},
    }
    with pytest.raises(ApiError) as error:
        Service(repo, "test").change("ENV-test", "review", {"version": 1})
    assert error.value.code == "INDEPENDENT_REVIEW_REQUIRED"
    repo.save.assert_not_called()


def test_platform_architect_cannot_author_environment_request():
    repo = MagicMock()
    repo.principal = Principal("architect", frozenset({"PLATFORM_ARCHITECT"}), frozenset(), True)
    with pytest.raises(ApiError) as error:
        Service(repo, "test").create({})
    assert error.value.status == 403
    repo.insert.assert_not_called()


def test_unauthenticated_metadata():
    result = lambda_handler(
        {"rawPath": "/api/v1/environments/metadata", "requestContext": {"http": {"method": "GET"}}},
        SimpleNamespace(aws_request_id="test"),
    )
    assert result["statusCode"] == 401


def test_gateway_routes_and_scopes():
    import yaml

    template = yaml.safe_load(Path("infrastructure/modules/environment-management/template.yaml").read_text())
    routes = [
        r["Properties"] for r in template["Resources"].values() if r["Type"] == "AWS::ApiGatewayV2::Route"
    ]
    assert len(routes) == 22
    assert all(
        r["AuthorizationType"] == "JWT" and r["AuthorizationScopes"] == [{"Ref": "JwtScope"}] for r in routes
    )
    assert (
        template["Resources"]["EnvironmentFunction"]["Properties"]["Handler"]
        == "navigan.modules.environment_management.handler.lambda_handler"
    )
    policies = template["Resources"]["EnvironmentFunction"]["Properties"]["Policies"]
    assert any(
        statement.get("Action") == "sts:AssumeRole"
        and statement["Resource"]["Fn::Sub"].endswith(":role/NaviganDiscoveryRole")
        for policy in policies
        if isinstance(policy, dict)
        for statement in policy.get("Statement", [])
    )
