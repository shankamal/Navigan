import getpass
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock
import urllib.error
import warnings

import pytest

spec = importlib.util.spec_from_file_location("domain_parity", Path(__file__).parents[1] / "scripts/validate-api-domain-parity.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
OLD = "https://dev123.execute-api.ap-south-1.amazonaws.com/v1/api/v1"
NEW = "https://api-dev.navigan.click/api/v1"
TOKEN = "private-test-token"
BODY = {"total": 1, "byStatus": {"ACTIVE": 1}, "byProvider": {}}


def opener(body=BODY, status=200):
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = status
    response.read.return_value = json.dumps(body).encode()
    client = MagicMock()
    client.open.return_value = response
    return client


def test_same_token_get_only_exact_summary_paths_and_no_redirects(monkeypatch):
    client = opener()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(m.urllib.request, "build_opener", factory)
    rows = m.compare(OLD, NEW, "Bearer " + TOKEN)
    assert len(rows) == 3 and all(row["passed"] for row in rows)
    factory.assert_called_once_with(m.release.NoRedirect)
    assert m.release.NoRedirect().redirect_request(None, None, 302, None, None, NEW) is None
    requests = [call.args[0] for call in client.open.call_args_list]
    assert [r.full_url for r in requests] == [base + path for path in m.ENDPOINTS for base in (OLD, NEW)]
    assert all(r.get_method() == "GET" and r.get_header("Authorization") == "Bearer " + TOKEN for r in requests)
    assert TOKEN not in json.dumps(rows) and "ACTIVE" not in json.dumps(rows)


@pytest.mark.parametrize("fault", ["401", "403", "302", "404", "500", "connection", "json", "list", "generic_object", "different", "oversize"])
def test_parity_requires_successful_matching_application_summaries(fault):
    client = opener()
    if fault.isdigit(): client.open.side_effect = urllib.error.HTTPError(NEW, int(fault), "private response", {}, io.BytesIO(TOKEN.encode()))
    elif fault == "connection": client.open.side_effect = urllib.error.URLError(TOKEN)
    elif fault == "json": client.open.return_value.read.return_value = b"not JSON"
    elif fault == "oversize": client.open.return_value.read.return_value = b"x" * (m.LIMIT + 1)
    elif fault in {"list", "generic_object"}: client.open.return_value.read.return_value = json.dumps([] if fault == "list" else {"message": TOKEN}).encode()
    else:
        response = client.open.return_value
        response.read.side_effect = [json.dumps(BODY).encode(), json.dumps({**BODY, "total": 2}).encode()] * 3
    rows = m.compare(OLD, NEW, TOKEN, opener=client)
    assert not any(row["passed"] for row in rows)
    assert TOKEN not in json.dumps(rows)


@pytest.mark.parametrize("raw", ["", " ", "token\nvalue", "token\rvalue", "two words", "token\x00value"])
def test_invalid_token_blocks_all_requests(raw):
    client = opener()
    with pytest.raises(ValueError): m.compare(OLD, NEW, raw, opener=client)
    client.open.assert_not_called()


def test_targets_bind_successful_verification_to_the_exact_plan(tmp_path, monkeypatch):
    path = tmp_path / "release-plan.json"
    plan = {"environment": "dev", "changeSet": "reviewed", "parameters": {"ApiId": "dev123", "DomainName": "api-dev.navigan.click"}}
    saved = {"environments": {"dev": {"existingBaseUrl": OLD}}}
    monkeypatch.setattr(m.release, "load_plan", MagicMock(return_value=(plan, saved, {}, {})))
    record = {"environment": "dev", "changeSet": "reviewed", "baseUrl": NEW, "oldEndpointRetained": True,
              "existingApiSettingsUnchanged": True, "tlsAndUnauthenticated401Verified": True}
    m.release.write(tmp_path / "verification.json", record)
    assert m.targets(path, "111111111111", "ap-south-1") == (plan, OLD, NEW)
    for key in record:
        bad = {**record, key: "incorrect"}
        m.release.write(tmp_path / "verification.json", bad)
        with pytest.raises(ValueError): m.targets(path, "111111111111", "ap-south-1")
    m.release.write(tmp_path / "verification.json", record)
    saved["environments"]["dev"]["existingBaseUrl"] = OLD.replace("dev123", "prod123")
    with pytest.raises(ValueError): m.targets(path, "111111111111", "ap-south-1")


def test_main_prompts_once_and_saves_only_private_status_evidence(tmp_path, monkeypatch, capsys):
    path = tmp_path / "release-plan.json"
    monkeypatch.setattr(sys, "argv", ["parity", "--release-plan", str(path), "--expected-account", "111111111111", "--region", "ap-south-1"])
    monkeypatch.setattr(m, "targets", MagicMock(return_value=({"environment": "dev", "changeSet": "reviewed"}, OLD, NEW)))
    prompt = MagicMock(return_value=TOKEN)
    monkeypatch.setattr(m.getpass, "getpass", prompt)
    monkeypatch.setattr(m.urllib.request, "build_opener", MagicMock(return_value=opener()))
    assert m.main() == 0
    prompt.assert_called_once_with("DEV bearer token (hidden): ")
    output = capsys.readouterr().out
    record = tmp_path / "authenticated-verification.json"
    assert TOKEN not in output + record.read_text() and "byStatus" not in output + record.read_text()
    assert record.stat().st_mode & 0o777 == 0o600
    assert m.release.read(record)["passed"] is True
    assert m.release.read(record)["frontendChanged"] is False


def test_noninteractive_token_echo_fallback_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["parity", "--release-plan", str(tmp_path / "plan"), "--expected-account", "111111111111", "--region", "ap-south-1"])
    monkeypatch.setattr(m, "targets", MagicMock(return_value=({"environment": "dev"}, OLD, NEW)))
    def fallback(prompt):
        warnings.warn("Cannot control echo", getpass.GetPassWarning)
        pytest.fail("Must stop before echoed input")
    monkeypatch.setattr(m.getpass, "getpass", fallback)
    with pytest.raises(getpass.GetPassWarning): m.main()
    assert not (tmp_path / "authenticated-verification.json").exists()
