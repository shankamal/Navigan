#!/usr/bin/env python3
"""Compare authenticated summary reads on one API's old and custom URLs.

Uses the verified private domain release plan, one hidden bearer token and GET
only. Response bodies and tokens are never printed or saved. No AWS mutations,
frontend changes or redirects are performed.
"""
import argparse
from datetime import datetime, timezone
import getpass
import importlib.util
import json
from pathlib import Path
import urllib.error
import urllib.request
import warnings

spec = importlib.util.spec_from_file_location("domain_release", Path(__file__).with_name("deploy-api-domain.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
require = release.require
ENDPOINTS = ("/customers/summary", "/environments/summary", "/clusters/summary")
LIMIT = 1024 * 1024


def targets(path, account, region):
    plan, original, _, _ = release.load_plan(path, account, region)
    record = release.read(path.parent / "verification.json")
    custom = "https://" + plan["parameters"]["DomainName"] + "/api/v1"
    require(record.get("environment") == plan["environment"] and record.get("changeSet") == plan["changeSet"]
            and record.get("baseUrl") == custom and record.get("oldEndpointRetained") is True
            and record.get("existingApiSettingsUnchanged") is True and record.get("tlsAndUnauthenticated401Verified") is True,
            "Matching successful domain verification is required before authenticated checks.")
    existing = "https://" + plan["parameters"]["ApiId"] + ".execute-api." + region + ".amazonaws.com/v1/api/v1"
    require(original["environments"][plan["environment"]]["existingBaseUrl"] == existing,
            "Saved existing endpoint does not match the selected API/region.")
    return plan, existing, custom


def token_value(raw):
    value = raw.strip()
    if value.lower().startswith("bearer "):
        value = value.split(None, 1)[1].strip()
    require(bool(value) and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value),
            "Bearer token is empty or malformed.")
    return value


def valid_summary(body):
    return (isinstance(body, dict) and type(body.get("total")) is int and body["total"] >= 0
            and all(isinstance(body.get(key), dict) and all(type(count) is int and count >= 0
                    for count in body[key].values()) for key in ("byStatus", "byProvider")))


def read_summary(opener, url, token):
    request = urllib.request.Request(url, method="GET", headers={
        "Authorization": "Bearer " + token, "Accept": "application/json",
        "User-Agent": "NaviganDomainParity/1"})
    try:
        with opener.open(request, timeout=30) as response:
            status = response.status
            if status != 200:
                return {"status": status, "error": "UNEXPECTED_STATUS"}, None
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                return {"status": status, "error": "RESPONSE_TOO_LARGE"}, None
            body = json.loads(raw)
            if not valid_summary(body):
                return {"status": status, "error": "INVALID_SUMMARY_JSON"}, None
            return {"status": status}, body
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        return {"status": status, "error": "HTTP_ERROR"}, None
    except (OSError, urllib.error.URLError):
        return {"status": None, "error": "CONNECTION_ERROR"}, None
    except (ValueError, UnicodeError):
        return {"status": None, "error": "INVALID_JSON"}, None


def compare(existing, custom, token, *, opener=None):
    token = token_value(token)
    opener = opener or urllib.request.build_opener(release.NoRedirect)
    results = []
    for endpoint in ENDPOINTS:
        old, old_body = read_summary(opener, existing + endpoint, token)
        new, new_body = read_summary(opener, custom + endpoint, token)
        matched = old_body is not None and new_body is not None and json.dumps(old_body, sort_keys=True) == json.dumps(new_body, sort_keys=True)
        results.append({"endpoint": endpoint, "existing": old, "custom": new, "sameJson": matched,
                        "passed": matched and old.get("status") == new.get("status") == 200})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-plan", required=True, type=Path)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    path = args.release_plan.resolve()
    plan, existing, custom = targets(path, args.expected_account, args.region)
    # getpass must never fall back to echoing input in a non-interactive shell.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        token = getpass.getpass(plan["environment"].upper() + " bearer token (hidden): ")
    results = compare(existing, custom, token)
    report = {"observedAt": datetime.now(timezone.utc).isoformat(), "environment": plan["environment"],
              "changeSet": plan["changeSet"], "readOnly": True, "frontendChanged": False,
              "passed": all(row["passed"] for row in results), "requests": results}
    release.write(path.parent / "authenticated-verification.json", report)
    print(json.dumps(report, indent=2))
    print(plan["environment"].upper() + " authenticated summary parity " + ("passed." if report["passed"] else "failed; inspect statuses. Concurrent data changes can also cause a JSON mismatch."))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception, getpass.GetPassWarning) as error:
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise SystemExit("Authenticated domain validation stopped: " + message + ". Tokens and response bodies are not recorded.")
