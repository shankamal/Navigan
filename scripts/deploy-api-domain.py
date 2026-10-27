#!/usr/bin/env python3
"""Stage or execute a new, additive API-domain companion stack.

Only a new certificate, regional domain, empty stage mapping and A alias are
allowed. The existing APIs, frontend, Lambda, backend and tools URLs stay intact.
--prepare never executes. --execute PLAN executes its exact CREATE change set.
--verify PLAN checks a completed deployment without repeating execution.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infrastructure/companion/api-domain.yaml"
spec = importlib.util.spec_from_file_location("api_domain_audit", Path(__file__).with_name("audit-api-domain-readiness.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
require = audit.require
FORMAT = "navigan-additive-api-domain-v1"
PROBE = "/api/v1/customers/summary"
TYPES = {"Certificate": "AWS::CertificateManager::Certificate", "ApiDomain": "AWS::ApiGatewayV2::DomainName",
         "RootMapping": "AWS::ApiGatewayV2::ApiMapping", "ApiDns": "AWS::Route53::RecordSet"}


def read(path):
    try:
        return json.loads(Path(path).read_text())
    except json.JSONDecodeError:
        raise ValueError("Invalid private JSON record: " + Path(path).name) from None


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")
    path.chmod(0o600)


def clean(value):
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items() if key != "ResponseMetadata"}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True, default=str).encode()).hexdigest()


def api_snapshot(observed):
    return {label: {key: (sorted(raw[key], key=lambda item: item[field]) if field else raw[key])
                   for key, field in (("api", None), ("stages", "StageName"), ("routes", "RouteId"),
                                      ("integrations", "IntegrationId"), ("authorizers", "AuthorizerId"))}
            for label, raw in observed["environments"].items()}


def checked_template():
    value = yaml.safe_load(TEMPLATE.read_text())
    require({name: item["Type"] for name, item in value["Resources"].items()} == TYPES, "Unexpected resource set in domain template.")
    require("ApiMappingKey" not in value["Resources"]["RootMapping"]["Properties"], "Only an empty root mapping is permitted.")
    return value


def delegation(zone_name, expected):
    """Verify public NS answers over HTTPS; no credentials or AWS mutations."""
    expected = {audit.normalized(name) for name in expected}
    require(expected, "Hosted zone nameservers are missing.")
    successes, failures = [], []
    for endpoint in ("https://dns.google/resolve", "https://cloudflare-dns.com/dns-query"):
        request = urllib.request.Request(endpoint + "?" + urllib.parse.urlencode({"name": zone_name, "type": "NS"}), headers={"Accept": "application/dns-json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.load(response)
            require(data.get("Status") == 0, "Public DNS resolver did not return a successful NS answer.")
            actual = {audit.normalized(item["data"]) for item in data.get("Answer", [])
                      if item.get("type") == 2 and audit.normalized(item.get("name", "")) == zone_name}
            require(actual == expected, "Public nameservers differ from the selected Route 53 zone; no deployment prepared.")
            successes.append(urllib.parse.urlsplit(endpoint).hostname)
        except ValueError:
            raise
        except (OSError, urllib.error.URLError):
            failures.append(urllib.parse.urlsplit(endpoint).hostname)
    require(successes, "Public DNS delegation could not be verified through either HTTPS resolver.")
    return {"zoneName": zone_name, "nameservers": sorted(expected), "verifiedBy": successes, "unreachableResolvers": failures}


def source_inputs(summary, expected_account, region):
    require(summary.get("readOnly") is True and summary.get("account") == expected_account and summary.get("region") == region
            and not summary.get("errors") and set(summary["environments"]) == {"dev", "prod"}, "Capture is not a complete matching two-environment audit.")
    for item in summary["environments"].values():
        require(not item.get("errors"), "Capture has an API/environment read error.")
    envs = summary["environments"]
    require(envs["dev"]["apiId"] != envs["prod"]["apiId"], "DEV and PROD must use distinct APIs.")
    zone = audit.normalized(summary["zoneName"])
    for label, prefix in (("dev", "api-dev."), ("prod", "api.")):
        item = envs[label]
        require(item["plannedDomain"] == prefix + zone and item["plannedStage"] == "v1" and item["plannedMappingPath"] == "",
                "Unexpected domain/stage/mapping target in the capture.")
    return argparse.Namespace(expected_account=expected_account, region=region, zone_name=zone,
        dev_api_id=envs["dev"]["apiId"], prod_api_id=envs["prod"]["apiId"],
        dev_domain=envs["dev"]["plannedDomain"], prod_domain=envs["prod"]["plannedDomain"], stage="v1")


def preflight(session, original, saved, args, environment, *, creating):
    current, observed = audit.audit(session, args)
    require(not current["errors"] and not any(item["errors"] for item in current["environments"].values()), "Fresh audit has read errors.")
    require(fingerprint(api_snapshot(observed)) == fingerprint(api_snapshot(saved)), "Existing API, stage, route, integration or authorization changed since capture.")
    require(current["dns"]["hostedZoneId"] == original["dns"]["hostedZoneId"]
            and set(current["dns"]["nameServers"]) == set(original["dns"]["nameServers"])
            and current["dns"]["caaRecords"] == original["dns"]["caaRecords"], "Hosted zone, nameservers or parent CAA changed.")
    target = current["environments"][environment]
    other = "prod" if environment == "dev" else "dev"
    require(fingerprint({key: observed["environments"][other].get(key) for key in ("domain", "mappings", "dnsRecords")})
            == fingerprint({key: saved["environments"][other].get(key) for key in ("domain", "mappings", "dnsRecords")}), "The other environment's custom-domain configuration changed.")
    require(any(route.get("RouteKey") == "GET " + PROBE and route.get("AuthorizationType") == "JWT"
                for route in observed["environments"][environment]["routes"]), "Expected JWT-protected read probe route is unavailable.")
    if creating:
        require(not target["domain"]["exists"] and not target["hasExistingAddressOrDelegationRecords"], "Target domain or address/delegation records already exist; refusing overwrite/import.")
        require(not target["matchingRegionalCertificates"], "Certificate candidates appeared; review reuse rather than request a duplicate.")
        require(fingerprint(target.get("dnsRecords", [])) == fingerprint(original["environments"][environment].get("dnsRecords", [])), "Target DNS records changed since capture.")
        require(not current["dns"]["caaRecords"] and not any(item["Type"] == "CAA" for item in target.get("dnsRecords", [])), "CAA records require explicit issuer review before a new certificate request.")
    proof = delegation(args.zone_name, current["dns"]["nameServers"])
    return current, observed, proof


def no_existing_stack(cfn, stack_name):
    try:
        cfn.describe_stacks(StackName=stack_name)
    except ClientError as error:
        require(error.response["Error"]["Code"] == "ValidationError" and "does not exist" in error.response["Error"].get("Message", ""), "Could not prove the new companion stack is absent.")
        return
    require(False, "Companion stack already exists. Inspect its plan/status; do not repeat preparation.")


def inspect_plan(cfn, plan):
    meta = cfn.describe_change_set(ChangeSetName=plan["changeSet"])
    # DescribeChangeSet does not return ChangeSetType. Prove a new stack via
    # its actual REVIEW_IN_PROGRESS state plus the exact additions-only plan.
    stacks = cfn.describe_stacks(StackName=plan["stackId"])["Stacks"]
    require(len(stacks) == 1 and stacks[0].get("StackId") == plan["stackId"] and stacks[0].get("StackName") == plan["stackName"]
            and stacks[0].get("StackStatus") == "REVIEW_IN_PROGRESS" and not stacks[0].get("ParentId"),
            "Change set does not target a new independent review stack.")
    require(meta.get("StackId") == plan["stackId"]
            and meta.get("Status") == "CREATE_COMPLETE" and meta.get("ExecutionStatus") == "AVAILABLE"
            and not meta.get("IncludeNestedStacks") and not meta.get("ParentChangeSetId")
            and not meta.get("ImportExistingResources"), "Prepared CREATE change set is not available and independent.")
    values = {item["ParameterKey"]: item.get("ParameterValue") for item in meta.get("Parameters", [])}
    require(len(values) == len(meta.get("Parameters", [])) and values == plan["parameters"], "Change-set parameters differ from the reviewed target.")
    raw = cfn.get_template(StackName=plan["stackId"], ChangeSetName=plan["changeSet"], TemplateStage="Original")["TemplateBody"]
    value = json.loads(raw) if isinstance(raw, str) else raw
    require(value == checked_template() and fingerprint(value) == plan["templateHash"], "Live or authored domain template differs from the saved plan.")
    changes = audit.pages(cfn, "describe_change_set", "Changes", ChangeSetName=plan["changeSet"])
    seen = set()
    for item in changes:
        row = item["ResourceChange"]
        name = row.get("LogicalResourceId")
        require(name in TYPES and name not in seen and row.get("ResourceType") == TYPES[name] and row.get("Action") == "Add"
                and row.get("Replacement") in (None, "False") and not row.get("PhysicalResourceId") and not row.get("ChangeSetId"), "Change set affects an existing or unexpected resource.")
        seen.add(name)
    require(seen == set(TYPES), "Change set must create exactly the four new companion resources.")


def prepare(session, capture, environment, account, region):
    original, saved = read(capture / "summary.json"), read(capture / "observations.json")
    args = source_inputs(original, account, region)
    require(saved.get("account") == account and saved.get("region") == region, "Private observations differ from the selected account/region.")
    current, _, dns = preflight(session, original, saved, args, environment, creating=True)
    target = current["environments"][environment]
    stack_name = "navigan-" + environment + "-api-domain"
    cfn = session.client("cloudformation")
    no_existing_stack(cfn, stack_name)
    template = checked_template()
    directory = Path(tempfile.mkdtemp(prefix="navigan-api-domain-release-"))
    directory.chmod(0o700)
    shutil.copytree(capture, directory / "baseline")
    print("Private domain release record: " + str(directory), flush=True)
    params = {"ApiId": target["apiId"], "StageName": "v1", "DomainName": target["plannedDomain"], "HostedZoneId": original["dns"]["hostedZoneId"].rsplit("/", 1)[-1]}
    write(directory / "delegation.json", dns)
    result = cfn.create_change_set(StackName=stack_name, ChangeSetName="api-domain-" + uuid.uuid4().hex[:12], ChangeSetType="CREATE",
        TemplateBody=json.dumps(template), IncludeNestedStacks=False, Parameters=[{"ParameterKey": key, "ParameterValue": value} for key, value in params.items()],
        Tags=[{"Key": "Application", "Value": "Navigan"}, {"Key": "Environment", "Value": environment}, {"Key": "Scope", "Value": "AdditiveApiDomain"}])
    plan = {"format": FORMAT, "account": account, "region": region, "environment": environment, "stackName": stack_name, "stackId": result["StackId"],
            "changeSet": result["Id"], "parameters": params, "templateHash": fingerprint(template)}
    path = directory / "release-plan.json"
    write(path, plan)
    print("Prepared unexecuted domain change set: " + result["Id"], flush=True)
    cfn.get_waiter("change_set_create_complete").wait(ChangeSetName=result["Id"], WaiterConfig={"Delay": 5, "MaxAttempts": 120})
    inspect_plan(cfn, plan)
    print("Scope verified: CREATE certificate, regional domain, empty mapping to existing v1 stage, and A alias only.", flush=True)
    print("No execution or frontend change. Release plan: " + str(path), flush=True)
    return path


def load_plan(path, account, region):
    plan = read(path)
    require(plan.get("format") == FORMAT and plan.get("account") == account and plan.get("region") == region
            and plan.get("environment") in {"dev", "prod"}, "Unexpected domain release plan/target.")
    require(plan["stackName"] == "navigan-" + plan["environment"] + "-api-domain"
            and plan["stackId"].startswith("arn:aws:cloudformation:" + region + ":" + account + ":stack/" + plan["stackName"] + "/"), "Unexpected companion stack identity.")
    original, saved = read(path.parent / "baseline/summary.json"), read(path.parent / "baseline/observations.json")
    args = source_inputs(original, account, region)
    target = original["environments"][plan["environment"]]
    require(plan["parameters"] == {"ApiId": target["apiId"], "StageName": "v1", "DomainName": target["plannedDomain"],
            "HostedZoneId": original["dns"]["hostedZoneId"].rsplit("/", 1)[-1]} and plan["templateHash"] == fingerprint(checked_template()), "Plan parameters or authored template changed.")
    return plan, original, saved, args


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def probe(url):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "NaviganDomainValidation/1"}), timeout=15) as response:
            return response.status
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        return code


def verify_certificate(acm, cert_arn, domain):
    # Describe the CFN-owned certificate itself: inventory listing can lag, and
    # another valid candidate must never establish validity for this resource.
    cert = acm.describe_certificate(CertificateArn=cert_arn)["Certificate"]
    require(cert.get("CertificateArn") == cert_arn and cert.get("DomainName") == domain,
            "Certificate identity/domain differs from the companion resource.")
    require(cert.get("Status") == "ISSUED", "Companion certificate is not ISSUED.")
    # ACM documents RSA-2048 in DescribeCertificate examples and RSA_2048 in
    # request/filter enums. Both denote the same exact key algorithm/size.
    require(cert.get("KeyAlgorithm") in {"RSA_2048", "RSA-2048"},
            "Companion certificate key algorithm is not RSA 2048.")
    before, after = cert.get("NotBefore"), cert.get("NotAfter")
    require(isinstance(before, datetime) and isinstance(after, datetime)
            and before.utcoffset() is not None and after.utcoffset() is not None,
            "Companion certificate validity timestamps are missing or invalid.")
    require(before <= datetime.now(timezone.utc) < after,
            "Companion certificate is outside its validity period.")


def verify(session, path, account, region):
    plan, original, saved, args = load_plan(path, account, region)
    cfn = session.client("cloudformation")
    stack = cfn.describe_stacks(StackName=plan["stackId"])["Stacks"][0]
    require(stack["StackStatus"] == "CREATE_COMPLETE", "Domain stack has not completed successfully; inspect AWS without recreating it.")
    require({item["ParameterKey"]: item["ParameterValue"] for item in stack["Parameters"]} == plan["parameters"], "Deployed stack parameters differ.")
    raw_template = cfn.get_template(StackName=plan["stackId"], TemplateStage="Original")["TemplateBody"]
    require((json.loads(raw_template) if isinstance(raw_template, str) else raw_template) == checked_template(), "Deployed domain template differs from the reviewed template.")
    resources = audit.pages(cfn, "list_stack_resources", "StackResourceSummaries", StackName=plan["stackId"])
    require(len(resources) == len(TYPES) and {item["LogicalResourceId"]: item["ResourceType"] for item in resources} == TYPES and all(item["ResourceStatus"] == "CREATE_COMPLETE" for item in resources), "Unexpected companion resources or incomplete creation.")
    cert_arn = next(item["PhysicalResourceId"] for item in resources if item["LogicalResourceId"] == "Certificate")
    current, observed, dns = preflight(session, original, saved, args, plan["environment"], creating=False)
    target = observed["environments"][plan["environment"]]
    configs = (target["domain"] or {}).get("DomainNameConfigurations", [])
    require(len(configs) == 1 and all(configs[0].get(key) == value for key, value in (
        ("EndpointType", "REGIONAL"), ("SecurityPolicy", "TLS_1_2"), ("DomainNameStatus", "AVAILABLE"), ("CertificateArn", cert_arn))), "Custom domain is not available with the reviewed regional TLS certificate.")
    mappings = target["mappings"]
    require(len(mappings) == 1 and mappings[0]["ApiId"] == plan["parameters"]["ApiId"] and mappings[0]["Stage"] == "v1" and not mappings[0].get("ApiMappingKey"), "Custom domain does not have the exact empty mapping to the existing API stage.")
    require(mappings[0]["ApiMappingId"] == next(item["PhysicalResourceId"] for item in resources if item["LogicalResourceId"] == "RootMapping"), "Root mapping identity differs from the new companion resource.")
    new_records = target["dnsRecords"]
    aliases = [item for item in new_records if item["Type"] == "A"]
    require(len(aliases) == 1 and aliases[0].get("AliasTarget", {}).get("EvaluateTargetHealth") is False
            and audit.normalized(aliases[0]["AliasTarget"]["DNSName"]) == audit.normalized(configs[0]["ApiGatewayDomainName"])
            and aliases[0]["AliasTarget"]["HostedZoneId"] == configs[0]["HostedZoneId"], "DNS A alias does not match the new regional endpoint.")
    require(fingerprint([item for item in new_records if item["Type"] != "A"]) == fingerprint(original["environments"][plan["environment"]].get("dnsRecords", [])), "Other target DNS records changed.")
    verify_certificate(session.client("acm"), cert_arn, plan["parameters"]["DomainName"])
    old = current["environments"][plan["environment"]]["existingBaseUrl"] + "/customers/summary"
    new = current["environments"][plan["environment"]]["plannedBaseUrl"] + "/customers/summary"
    require(probe(old) == 401, "Existing JWT-protected endpoint did not return expected unauthenticated HTTP 401.")
    for attempt in range(12):
        try:
            status = probe(new)
            if status == 401:
                break
            require(attempt < 11, "New domain returned an unexpected HTTP status. Retry --verify with this plan after inspecting propagation; do not recreate the stack.")
            print("Waiting for new-domain route propagation (HTTP " + str(status) + ")...", flush=True)
            time.sleep(5)
        except (OSError, urllib.error.URLError):
            if attempt == 11:
                raise ValueError("New-domain DNS/TLS is still propagating. Retry --verify with this plan; do not recreate the stack.") from None
            print("Waiting for new-domain DNS/TLS propagation...", flush=True)
            time.sleep(5)
    record = {"verifiedAt": datetime.now(timezone.utc).isoformat(), "environment": plan["environment"], "changeSet": plan["changeSet"],
              "baseUrl": current["environments"][plan["environment"]]["plannedBaseUrl"], "oldEndpointRetained": True,
              "existingApiSettingsUnchanged": True, "tlsAndUnauthenticated401Verified": True, "authenticatedAcceptance": False, "frontendChanged": False, "delegation": dns}
    write(path.parent / "verification.json", record)
    print(plan["environment"].upper() + " API custom domain verified; old endpoint/API settings retained. Frontend unchanged. Authenticated parity remains required.", flush=True)


def execute(session, path, account, region):
    plan, original, saved, args = load_plan(path, account, region)
    journal = path.parent / "execution.json"
    require(not journal.exists(), "Execution already requested. Inspect the journal/AWS or use --verify after completion; do not execute again.")
    preflight(session, original, saved, args, plan["environment"], creating=True)
    cfn = session.client("cloudformation")
    require(cfn.describe_stacks(StackName=plan["stackId"])["Stacks"][0]["StackStatus"] == "REVIEW_IN_PROGRESS", "CREATE plan no longer targets a new review stack.")
    inspect_plan(cfn, plan)
    token = "api-domain-" + uuid.uuid4().hex
    write(journal, {"requestedAt": datetime.now(timezone.utc).isoformat(), "changeSet": plan["changeSet"], "clientRequestToken": token})
    cfn.execute_change_set(ChangeSetName=plan["changeSet"], ClientRequestToken=token)
    print("Creating only the new " + plan["environment"].upper() + " certificate/domain/mapping/DNS resources...", flush=True)
    cfn.get_waiter("stack_create_complete").wait(StackName=plan["stackId"], WaiterConfig={"Delay": 10, "MaxAttempts": 180})
    verify(session, path, account, region)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="navigan")
    parser.add_argument("--region", required=True)
    parser.add_argument("--expected-account", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", type=Path)
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--environment", choices=("dev", "prod"))
    args = parser.parse_args()
    require(re.fullmatch(r"[0-9]{12}", args.expected_account), "Provide the explicit expected account.")
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    require(session.client("sts").get_caller_identity()["Account"] == args.expected_account, "Unexpected AWS account.")
    if args.prepare:
        require(args.capture is not None and args.environment is not None, "Preparation requires --capture and --environment.")
        prepare(session, args.capture.resolve(), args.environment, args.expected_account, args.region)
    else:
        require(args.capture is None and args.environment is None, "Resume/verification target comes only from the saved plan.")
        (execute if args.execute else verify)(session, (args.execute or args.verify).resolve(), args.expected_account, args.region)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise SystemExit("API domain release stopped: " + message + ". Keep private records local; inspect existing state before retrying.")
