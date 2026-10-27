#!/usr/bin/env python3
"""Read-only inventory before adding custom domains to existing HTTP API stages.

No AWS writes, change sets, certificate requests, DNS changes, frontend updates
or HTTP probes. Share summary.json only; full observations remain private.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


KEY_TYPES = ["RSA_1024", "RSA_2048", "RSA_3072", "RSA_4096", "EC_prime256v1", "EC_secp384r1", "EC_secp521r1"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normalized(name):
    return name.lower().rstrip(".")


def covers(pattern, hostname):
    pattern, hostname = normalized(pattern), normalized(hostname)
    return pattern == hostname or (pattern.startswith("*.") and pattern.count("*") == 1
        and hostname.endswith(pattern[1:]) and len(hostname.split(".")) == len(pattern.split(".")))


def pages(client, operation, key, **kwargs):
    rows, token = [], None
    while True:
        response = getattr(client, operation)(**kwargs, **({"NextToken": token} if token else {}))
        rows.extend(response.get(key, []))
        token = response.get("NextToken")
        if not token:
            return rows


def failure(scope, error):
    code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
    return {"scope": scope, "code": code, **({"detail": str(error)} if isinstance(error, ValueError) else {})}


def dns_records(route53, zone_id, name):
    """Read exact-name records only; stop before unrelated record names."""
    rows, request = [], {"HostedZoneId": zone_id, "StartRecordName": name + ".", "MaxItems": "100"}
    while True:
        page = route53.list_resource_record_sets(**request)
        for row in page.get("ResourceRecordSets", []):
            if normalized(row["Name"]) != normalized(name):
                return rows
            rows.append(row)
        if not page.get("IsTruncated") or normalized(page["NextRecordName"]) != normalized(name):
            return rows
        request = {"HostedZoneId": zone_id, "StartRecordName": page["NextRecordName"], "StartRecordType": page["NextRecordType"], "MaxItems": "100"}
        if page.get("NextRecordIdentifier"):
            request["StartRecordIdentifier"] = page["NextRecordIdentifier"]


def mapping_summary(mappings, api_id, stage):
    return [{"path": item.get("ApiMappingKey", ""), "apiId": item["ApiId"], "stage": item["Stage"],
             "matchesPlannedRoot": item.get("ApiMappingKey", "") == "" and item["ApiId"] == api_id and item["Stage"] == stage}
            for item in mappings]


def audit(session, args):
    account = session.client("sts").get_caller_identity()["Account"]
    require(account == args.expected_account, "AWS account differs from the explicit expected account.")
    gateway, route53, acm = (session.client(name) for name in ("apigatewayv2", "route53", "acm"))
    observed = {"observedAt": datetime.now(timezone.utc).isoformat(), "account": account, "region": args.region, "environments": {}}
    summary = {"readOnly": True, "deploymentReady": False, "account": account, "region": args.region,
               "zoneName": args.zone_name, "environments": {}, "errors": []}
    zones = []
    try:
        for page in route53.get_paginator("list_hosted_zones").paginate():
            zones.extend(zone for zone in page["HostedZones"] if normalized(zone["Name"]) == args.zone_name and not zone.get("Config", {}).get("PrivateZone"))
        observed["matchingPublicZones"] = zones
        require(len(zones) == 1, "Expected exactly one public hosted zone for the requested parent domain.")
        zone = route53.get_hosted_zone(Id=zones[0]["Id"])
        observed["zone"] = zone
        summary["dns"] = {"hostedZoneId": zones[0]["Id"], "nameServers": zone.get("DelegationSet", {}).get("NameServers", []),
                          "publicDelegationVerified": False, "caaRecords": dns_records(route53, zones[0]["Id"], args.zone_name)}
        summary["dns"]["caaRecords"] = [record for record in summary["dns"]["caaRecords"] if record["Type"] == "CAA"]
    except Exception as error:
        summary["errors"].append(failure("route53", error))
        zones = []
    certificates = []
    try:
        for page in acm.get_paginator("list_certificates").paginate(Includes={"keyTypes": KEY_TYPES}):
            for item in page.get("CertificateSummaryList", []):
                certificates.append(acm.describe_certificate(CertificateArn=item["CertificateArn"])["Certificate"])
        observed["certificates"] = certificates
    except Exception as error:
        summary["errors"].append(failure("acm", error))
    now = datetime.now(timezone.utc)
    for label, api_id, domain in (("dev", args.dev_api_id, args.dev_domain), ("prod", args.prod_api_id, args.prod_domain)):
        raw = {}
        observed["environments"][label] = raw
        result = {"apiId": api_id, "plannedDomain": domain, "plannedBaseUrl": "https://" + domain + "/api/v1",
                  "plannedStage": args.stage, "plannedMappingPath": "", "errors": []}
        summary["environments"][label] = result
        try:
            raw["api"] = gateway.get_api(ApiId=api_id)
            require(raw["api"]["ApiId"] == api_id and raw["api"]["ProtocolType"] == "HTTP", "Selected API is not the expected HTTP API.")
            endpoint = "https://" + api_id + ".execute-api." + args.region + ".amazonaws.com"
            require(raw["api"]["ApiEndpoint"].rstrip("/") == endpoint, "Unexpected API endpoint or region.")
            raw["stages"] = pages(gateway, "get_stages", "Items", ApiId=api_id)
            require(any(stage["StageName"] == args.stage for stage in raw["stages"]), "Existing target stage was not found; no stage creation is planned.")
            for operation, key in (("get_routes", "routes"), ("get_integrations", "integrations"), ("get_authorizers", "authorizers")):
                raw[key] = pages(gateway, operation, "Items", ApiId=api_id)
            result.update({"existingBaseUrl": endpoint + "/" + args.stage + "/api/v1", "defaultEndpointEnabled": not raw["api"].get("DisableExecuteApiEndpoint", False),
                           "stages": [{"name": stage["StageName"], "autoDeploy": stage.get("AutoDeploy", False)} for stage in raw["stages"]],
                           "routeCount": len(raw["routes"]), "authorizerCount": len(raw["authorizers"]), "cors": raw["api"].get("CorsConfiguration")})
            require(result["defaultEndpointEnabled"], "Default execute-api endpoint is disabled; retention requirement needs review.")
        except Exception as error:
            result["errors"].append(failure("api", error))
        try:
            try:
                raw["domain"] = gateway.get_domain_name(DomainName=domain)
            except ClientError as error:
                if error.response["Error"]["Code"] != "NotFoundException":
                    raise
                raw["domain"] = None
            raw["mappings"] = [] if raw["domain"] is None else pages(gateway, "get_api_mappings", "Items", DomainName=domain)
            result["domain"] = {"exists": raw["domain"] is not None,
                "configurations": [{key: entry.get(key) for key in ("EndpointType", "SecurityPolicy", "DomainNameStatus", "ApiGatewayDomainName", "HostedZoneId")} for entry in (raw["domain"] or {}).get("DomainNameConfigurations", [])],
                "routingMode": (raw["domain"] or {}).get("RoutingMode"), "mappings": mapping_summary(raw["mappings"], api_id, args.stage)}
        except Exception as error:
            result["errors"].append(failure("custom-domain", error))
        if zones:
            try:
                raw["dnsRecords"] = dns_records(route53, zones[0]["Id"], domain)
                result["dnsRecords"] = raw["dnsRecords"]
                result["hasExistingAddressOrDelegationRecords"] = any(record["Type"] in {"A", "AAAA", "CNAME", "NS"} for record in raw["dnsRecords"])
            except Exception as error:
                result["errors"].append(failure("domain-dns", error))
        candidates = []
        for certificate in certificates:
            names = certificate.get("SubjectAlternativeNames") or [certificate["DomainName"]]
            if not any(covers(name, domain) for name in names):
                continue
            candidates.append({"certificateRef": certificate["CertificateArn"].rsplit("/", 1)[-1], "status": certificate["Status"],
                               "names": names, "keyAlgorithm": certificate.get("KeyAlgorithm"), "notAfter": certificate.get("NotAfter"),
                               "issuedAndTimeValid": certificate["Status"] == "ISSUED" and certificate.get("NotBefore", now) <= now < certificate.get("NotAfter", now),
                               "inUseCount": len(certificate.get("InUseBy", []))})
        result["matchingRegionalCertificates"] = candidates
        result["hasIssuedTimeValidCertificate"] = any(item["issuedAndTimeValid"] for item in candidates)
    summary["observedAt"] = observed["observedAt"]
    return summary, observed


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--profile", default="navigan")
    result.add_argument("--region", required=True)
    result.add_argument("--expected-account", required=True)
    result.add_argument("--zone-name", default="navigan.click")
    result.add_argument("--dev-api-id", required=True)
    result.add_argument("--prod-api-id", required=True)
    result.add_argument("--dev-domain", default="api-dev.navigan.click")
    result.add_argument("--prod-domain", default="api.navigan.click")
    result.add_argument("--stage", default="v1")
    return result


def main():
    args = parser().parse_args()
    args.zone_name, args.dev_domain, args.prod_domain = map(normalized, (args.zone_name, args.dev_domain, args.prod_domain))
    require(re.fullmatch(r"[0-9]{12}", args.expected_account), "Provide the explicit expected AWS account.")
    require(re.fullmatch(r"[a-z0-9]+", args.dev_api_id) and re.fullmatch(r"[a-z0-9]+", args.prod_api_id) and args.dev_api_id != args.prod_api_id,
            "Provide two distinct HTTP API IDs.")
    require(args.dev_domain != args.prod_domain and all(name.endswith("." + args.zone_name) for name in (args.dev_domain, args.prod_domain)),
            "Provide distinct custom domains beneath the selected parent zone.")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    session_args = {"region_name": args.region, "config": Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 2})}
    class Clients:
        def client(self, name):
            return session.client(name, **session_args)
    summary, observations = audit(Clients(), args)
    directory = Path(tempfile.mkdtemp(prefix="navigan-api-domain-audit-"))
    directory.chmod(0o700)
    for name, data in (("summary.json", summary), ("observations.json", observations)):
        path = directory / name
        path.write_text(json.dumps(data, indent=2, default=str) + "\n")
        path.chmod(0o600)
    print(json.dumps(summary, indent=2, default=str))
    print("Private read-only capture: " + str(directory))
    print("Share summary.json only. No AWS resources or frontend settings were changed.")
    return 2 if summary["errors"] or any(env["errors"] for env in summary["environments"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
