"""Verify the scoped workspace rollout's transaction and database boundaries."""
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workspace_migrate", ROOT / "scripts/migrate_data_api.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class DataAPI:
    def __init__(self, *, fail=False, missing=False, checksums=None):
        self.calls = []
        self.committed = False
        self.rolled_back = False
        self.fail = fail
        self.missing = missing
        self.checksums = checksums or {}

    def begin_transaction(self, **kwargs):
        assert kwargs["database"] == "navigan_dev"
        return {"transactionId": "transaction"}

    def execute_statement(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["transactionId"] == "transaction"
        sql = kwargs["sql"]
        if sql == "SELECT current_database()":
            return {"records": [[{"stringValue": "navigan_dev"}]]}
        if sql.startswith("SELECT checksum"):
            name = kwargs["parameters"][0]["value"]["stringValue"]
            return {"records": [[{"stringValue": self.checksums[name]}]] if name in self.checksums else []}
        if self.fail and sql.startswith("CREATE TABLE migration_management"):
            raise RuntimeError("simulated DDL failure")
        if sql.startswith("SELECT to_regclass"):
            return {"records": [[{"isNull": True} if self.missing else {"stringValue": "table"}]]}
        return {"records": []}

    def commit_transaction(self, **kwargs):
        self.committed = True

    def rollback_transaction(self, **kwargs):
        self.rolled_back = True


def setup(monkeypatch, client, *extra):
    monkeypatch.setattr(sys, "argv", ["runner", "--profile", "navigan", "--region", "ap-south-1",
                                    "--resource-arn", "cluster", "--secret-arn", "secret",
                                    "--database", "navigan_dev", "--workspace-only",
                                    "--migrations-dir", str(ROOT / "database/migrations"), *extra])
    class Session:
        def __init__(self, **kwargs):
            pass
        def client(self, name):
            return client
    monkeypatch.setattr(runner.boto3, "Session", Session)


def test_scoped_rollout_has_one_transaction_and_original_checksums(monkeypatch):
    client = DataAPI()
    setup(monkeypatch, client)
    assert runner.main() == 0
    assert client.committed and not client.rolled_back
    sql = [call["sql"] for call in client.calls]
    assert not any(statement.upper() in {"BEGIN", "COMMIT", "ROLLBACK"} for statement in sql)
    creates = [statement for statement in sql if statement.startswith("CREATE TABLE migration_management")]
    assert len(creates) == 3
    grants = [statement for statement in sql if statement.startswith("GRANT")]
    assert grants == [runner.WORKSPACE_GRANTS.strip().rstrip(";")]
    tracked = [call for call in client.calls if call["sql"].startswith("INSERT INTO platform.schema_migrations")]
    assert len(tracked) == 2
    for call, name in zip(tracked, runner.WORKSPACE_MIGRATIONS):
        values = {param["name"]: param["value"]["stringValue"] for param in call["parameters"]}
        assert values == {"name": name, "checksum": hashlib.sha256((ROOT / "database/migrations" / name).read_bytes()).hexdigest()}


@pytest.mark.parametrize("options", [{"fail": True}, {"missing": True}, {"checksums": {runner.WORKSPACE_MIGRATIONS[0]: "modified"}}])
def test_failure_rolls_back_without_commit(monkeypatch, options):
    client = DataAPI(**options)
    setup(monkeypatch, client)
    with pytest.raises(RuntimeError):
        runner.main()
    assert client.rolled_back and not client.committed


def test_dry_run_makes_no_aws_calls(monkeypatch):
    setup(monkeypatch, None, "--dry-run")
    monkeypatch.setattr(runner.boto3, "Session", lambda **kwargs: pytest.fail("AWS called"))
    assert runner.main() == 0


def test_workspace_mode_refuses_production_even_with_override(monkeypatch):
    setup(monkeypatch, None, "--database", "navigan", "--confirm-production-database", "navigan")
    with pytest.raises(SystemExit, match="requires --database navigan_dev"):
        runner.main()


def test_repeat_run_skips_ddl(monkeypatch):
    checksums = {name: hashlib.sha256((ROOT / "database/migrations" / name).read_bytes()).hexdigest()
                 for name in runner.WORKSPACE_MIGRATIONS}
    client = DataAPI(checksums=checksums)
    setup(monkeypatch, client)
    assert runner.main() == 0
    assert not any(call["sql"].startswith("CREATE TABLE migration_management") for call in client.calls)
    assert client.committed
