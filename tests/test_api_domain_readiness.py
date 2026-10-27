from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from unittest.mock import MagicMock

from botocore.exceptions import ClientError
import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("domain_readiness", ROOT / "scripts/audit-api-domain-readiness.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def argv():
    return ["--region", "ap-south-1", "--expected-account", "111111111111", "--dev-api-id", "dev123", "--prod-api-id", "prod123"]


def fixture():
    clients = {name: MagicMock() for name in ("sts", "apigatewayv2", "route53", "acm")}
    session = MagicMock()
    session.client.side_effect = lambda name, **kwargs: clients[name]
    clients["sts"].get_caller_identity.return_value = {"Account": "111111111111"}
    clients["route53"].get_paginator.return_value.paginate.return_value = [{"HostedZones": [
        {"Id": "private", "Name": "navigan.click.", "Config": {"PrivateZone": True}},
        {"Id": "public", "Name": "navigan.click.", "Config": {"PrivateZone": False}}]}]
    clients["route53"].get_hosted_zone.return_value = {"DelegationSet": {"NameServers": ["ns1.example.test"]}}
    clients["route53"].list_resource_record_sets.return_value = {"ResourceRecordSets": []}
    now = datetime.now(timezone.utc)
    clients["acm"].get_paginator.return_value.paginate.return_value = [{"CertificateSummaryList": [{"CertificateArn": "arn:aws:acm:ap-south-1:111111111111:certificate/test"}]}]
    clients["acm"].describe_certificate.return_value = {"Certificate": {
        "CertificateArn": "arn:aws:acm:ap-south-1:111111111111:certificate/test", "DomainName": "*.navigan.click", "SubjectAlternativeNames": ["*.navigan.click"],
        "Status": "ISSUED", "KeyAlgorithm": "EC_prime256v1", "NotBefore": now - timedelta(days=1), "NotAfter": now + timedelta(days=30)}}
    gateway = clients["apigatewayv2"]
    gateway.get_api.side_effect = lambda ApiId: {"ApiId": ApiId, "ProtocolType": "HTTP", "ApiEndpoint": "https://" + ApiId + ".execute-api.ap-south-1.amazonaws.com"}
    gateway.get_stages.return_value = {"Items": [{"StageName": "v1", "AutoDeploy": True}]}
    gateway.get_routes.side_effect = lambda **kwargs: {"Items": [{"RouteId": "one"}], **({"NextToken": "next"} if "NextToken" not in kwargs else {})}
    gateway.get_integrations.return_value = {"Items": []}
    gateway.get_authorizers.return_value = {"Items": [{"AuthorizerType": "JWT"}]}
    gateway.get_domain_name.side_effect = ClientError({"Error": {"Code": "NotFoundException", "Message": "absent"}}, "GetDomainName")
    return session, clients, m.parser().parse_args(argv())


@pytest.mark.parametrize("pattern,host,expected", [
    ("*.navigan.click", "api-dev.navigan.click", True), ("*.navigan.click", "api.navigan.click", True),
    ("*.navigan.click", "navigan.click", False), ("*.navigan.click", "deep.api.navigan.click", False),
    ("api.navigan.click", "api-dev.navigan.click", False), ("API.NAVIGAN.CLICK.", "api.navigan.click", True),
    ("*.*.click", "api.navigan.click", False), ("*.example.test", "api.navigan.click", False)])
def test_certificate_hostname_coverage_obeys_single_label_wildcards(pattern, host, expected):
    assert m.covers(pattern, host) is expected


def test_audit_is_read_only_paginates_and_preserves_existing_stages_and_default_endpoints():
    session, clients, args = fixture()
    summary, raw = m.audit(session, args)
    assert not summary["errors"] and not summary["deploymentReady"]
    assert summary["dns"]["hostedZoneId"] == "public"
    assert summary["dns"]["publicDelegationVerified"] is False
    for label in ("dev", "prod"):
        result = summary["environments"][label]
        assert not result["errors"] and not result["domain"]["exists"]
        assert result["routeCount"] == 2 and result["hasIssuedTimeValidCertificate"]
        assert result["plannedMappingPath"] == "" and result["plannedStage"] == "v1"
        assert result["existingBaseUrl"].endswith("/v1/api/v1") and result["plannedBaseUrl"].endswith("/api/v1")
        assert result["defaultEndpointEnabled"]
    assert clients["acm"].get_paginator.return_value.paginate.call_args.kwargs["Includes"]["keyTypes"] == m.KEY_TYPES
    allowed = {"sts": {"get_caller_identity"}, "apigatewayv2": {"get_api", "get_stages", "get_routes", "get_integrations", "get_authorizers", "get_domain_name"},
               "route53": {"get_paginator", "get_hosted_zone", "list_resource_record_sets"}, "acm": {"get_paginator", "describe_certificate"}}
    for name, client in clients.items():
        assert all(call[0].split(".")[0] in allowed[name] for call in client.method_calls)
    assert set(raw["environments"]["dev"]) >= {"api", "stages", "routes", "integrations", "authorizers", "domain", "mappings", "dnsRecords"}


@pytest.mark.parametrize("fault", ["account", "zone", "stage", "protocol", "endpoint", "default_disabled", "domain_denied", "acm_denied"])
def test_missing_conflicting_or_unreadable_prerequisites_are_reported_without_writes(fault):
    session, clients, args = fixture()
    if fault == "account":
        args.expected_account = "222222222222"
        with pytest.raises(ValueError): m.audit(session, args)
        assert session.client.call_count == 1
        return
    if fault == "zone": clients["route53"].get_paginator.return_value.paginate.return_value = [{"HostedZones": []}]
    elif fault == "stage": clients["apigatewayv2"].get_stages.return_value = {"Items": [{"StageName": "other"}]}
    elif fault in {"protocol", "endpoint", "default_disabled"}:
        old = clients["apigatewayv2"].get_api.side_effect
        def changed(**kwargs):
            result = old(**kwargs)
            result[{"protocol": "ProtocolType", "endpoint": "ApiEndpoint", "default_disabled": "DisableExecuteApiEndpoint"}[fault]] = {
                "protocol": "WEBSOCKET", "endpoint": "https://other.example.test", "default_disabled": True}[fault]
            return result
        clients["apigatewayv2"].get_api.side_effect = changed
    else:
        target = clients["apigatewayv2"].get_domain_name if fault == "domain_denied" else clients["acm"].describe_certificate
        target.side_effect = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "private error value"}}, "Read")
    summary, _ = m.audit(session, args)
    assert summary["errors"] or any(env["errors"] for env in summary["environments"].values())
    assert "private error value" not in str(summary)
    assert not summary["deploymentReady"]


@pytest.mark.parametrize("status,delta,expected", [("ISSUED", 5, True), ("ISSUED", -1, False), ("PENDING_VALIDATION", 5, False), ("REVOKED", 5, False)])
def test_pending_revoked_and_expired_certificates_are_not_treated_as_issued_candidates(status, delta, expected):
    session, clients, args = fixture()
    cert = clients["acm"].describe_certificate.return_value["Certificate"]
    cert.update(Status=status, NotAfter=datetime.now(timezone.utc) + timedelta(days=delta))
    summary, _ = m.audit(session, args)
    assert summary["environments"]["dev"]["hasIssuedTimeValidCertificate"] is expected


def test_existing_mapping_and_dns_are_reported_instead_of_overwritten():
    session, clients, args = fixture()
    gateway = clients["apigatewayv2"]
    gateway.get_domain_name.side_effect = None
    gateway.get_domain_name.return_value = {"DomainNameConfigurations": [{"EndpointType": "REGIONAL", "SecurityPolicy": "TLS_1_2", "DomainNameStatus": "AVAILABLE"}]}
    gateway.get_api_mappings.return_value = {"Items": [{"ApiId": "other", "Stage": "v1", "ApiMappingKey": ""}]}
    clients["route53"].list_resource_record_sets.side_effect = lambda **kwargs: {"ResourceRecordSets": [{"Name": kwargs["StartRecordName"], "Type": "CNAME", "ResourceRecords": [{"Value": "existing.example.test"}]}]}
    summary, _ = m.audit(session, args)
    result = summary["environments"]["dev"]
    assert result["domain"]["exists"] and not result["domain"]["mappings"][0]["matchesPlannedRoot"]
    assert result["hasExistingAddressOrDelegationRecords"]


def test_dns_inventory_stops_at_other_names_and_paginates_same_name_routing_records():
    client = MagicMock()
    client.list_resource_record_sets.side_effect = [
        {"ResourceRecordSets": [{"Name": "api.example.test.", "Type": "A"}], "IsTruncated": True, "NextRecordName": "api.example.test.", "NextRecordType": "A", "NextRecordIdentifier": "weighted-two"},
        {"ResourceRecordSets": [{"Name": "api.example.test.", "Type": "A"}, {"Name": "other.example.test.", "Type": "TXT", "ResourceRecords": [{"Value": "do not report"}]}]}]
    rows = m.dns_records(client, "zone", "api.example.test")
    assert len(rows) == 2 and "do not report" not in str(rows)
    assert client.list_resource_record_sets.call_args.kwargs["StartRecordIdentifier"] == "weighted-two"


def test_main_saves_private_records_without_creating_an_apply_option(tmp_path, monkeypatch, capsys):
    session, _, _ = fixture()
    monkeypatch.setattr(sys, "argv", ["audit", *argv()])
    monkeypatch.setattr(m.boto3, "Session", lambda **kwargs: session)
    monkeypatch.setattr(m.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path))
    assert m.main() == 0
    assert (tmp_path.stat().st_mode & 0o777) == 0o700
    for name in ("summary.json", "observations.json"):
        assert ((tmp_path / name).stat().st_mode & 0o777) == 0o600
    assert "No AWS resources or frontend settings were changed" in capsys.readouterr().out
    with pytest.raises(SystemExit): m.parser().parse_args([*argv(), "--apply"])
