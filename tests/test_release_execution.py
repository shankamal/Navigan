"""Offline release-contract tests: no live AWS, Docker or database mutations."""
import base64
import copy
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import boto3
from botocore.exceptions import ClientError
from botocore.stub import Stubber
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_common as common
import release_database as database
import release_dev_target as target

build = common.load("tested_build_release", common.ROOT / "scripts/build-release.py")
deploy = common.load("tested_dev_release", common.ROOT / "scripts/deploy-release-dev.py")
ACCOUNT = "123456789012"
REGION = "ap-south-1"
STACK = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{common.DEV_STACK}/fixed"
REVISION = "a" * 40


def error(code):
    return ClientError({"Error": {"Code": code, "Message": "fixture"}}, "Fixture")


class MemoryS3:
    def __init__(self):
        self.objects, self.calls, self.next_version = {}, [], 0

    def put_object(self, **kw):
        self.calls.append(("put", kw))
        key = (kw["Bucket"], kw["Key"])
        old = self.objects.get(key)
        if kw.get("IfNoneMatch") == "*" and old:
            raise error("PreconditionFailed")
        if kw.get("IfMatch") and (not old or kw["IfMatch"] != old["ETag"]):
            raise error("PreconditionFailed")
        self.next_version += 1
        value = {"Body": kw["Body"], "VersionId": str(self.next_version), "ETag": '"' + str(self.next_version) + '"'}
        self.objects[key] = value
        return {key: value[key] for key in ("VersionId", "ETag")}

    def get_object(self, **kw):
        self.calls.append(("get", kw))
        value = self.objects.get((kw["Bucket"], kw["Key"]))
        if not value:
            raise error("NoSuchKey")
        if kw.get("VersionId") and kw["VersionId"] != value["VersionId"]:
            raise error("NoSuchVersion")
        return {**value, "ContentLength": len(value["Body"]), "Body": io.BytesIO(value["Body"])}

    def head_object(self, **kw):
        value = self.objects.get((kw["Bucket"], kw["Key"]))
        if not value:
            raise error("404")
        return {"VersionId": value["VersionId"]}

    def delete_object(self, **kw):
        self.calls.append(("delete", kw))
        key = (kw["Bucket"], kw["Key"])
        if self.objects.get(key, {}).get("VersionId") == kw["VersionId"]:
            del self.objects[key]


def session(s3=None, **clients):
    return SimpleNamespace(client=lambda name: s3 if name == "s3" else clients[name], region_name=REGION)


def config():
    return {"format": "navigan-dev-release-config-v1", "environment": "dev", "stack": common.DEV_STACK,
            "database": common.DEV_DATABASE, "apiOrigin": common.DEV_API, "apiBasePath": "/api/v1",
            "account": ACCOUNT, "region": REGION, "rootStackId": STACK, "artifactBucket": "fixture-artifacts",
            "frontend": {"mode": "local-preview", "port": 3001, "publicEnvironment": {
                "NAVIGAN_PUBLIC_APP_URL": "http://localhost:3001", "NAVIGAN_PUBLIC_OIDC_CLIENT_ID": "devclient"}},
            "parameterOverrides": {}, "imageWorkerEnabled": False}


def artifact(name="backend", seed="a"):
    digest = seed * 64
    item = {"inputHash": "c" * 64, "sha256": digest, "portable": True, "buildContract": common.CONTRACT}
    if name in common.planner.IMAGES:
        item["uri"] = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{common.REGISTRY_PREFIX}/{name}@sha256:{digest}"
    else:
        item.update(uri=f"s3://fixture-artifacts/{name}.zip", versionId="1")
    return item


def manifest(**components):
    return {"format": common.planner.FORMAT, "sourceRevision": REVISION, "components": components}


@pytest.mark.parametrize("name", ["/etc/passwd", "../secret", "a/../../secret", "a\\b"])
def test_archive_rejects_unsafe_members(name):
    with pytest.raises(common.ReleaseError):
        common.deterministic_zip({name: b"x"})


def test_archive_is_reproducible_and_rejects_symlinks_and_duplicates():
    assert common.deterministic_zip({"b": b"2", "a": b"1"}) == common.deterministic_zip({"a": b"1", "b": b"2"})
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as out:
        item = zipfile.ZipInfo("link")
        item.external_attr = 0o120777 << 16
        out.writestr(item, "/private")
    with pytest.raises(common.ReleaseError):
        common.unzip(stream.getvalue())
    with pytest.raises(common.ReleaseError):
        common.unzip(common.deterministic_zip({"x": b"123"}), maximum=2)


def test_content_address_reuses_exact_version_and_verifies_bytes():
    s3 = MemoryS3()
    one = common.put_content(s3, "fixture-artifacts", "objects/a", b"same", ACCOUNT)
    two = common.put_content(s3, "fixture-artifacts", "objects/a", b"same", ACCOUNT)
    assert one == two
    assert len([row for row in s3.calls if row[0] == "put"]) == 1
    assert common.object_bytes(s3, one, ACCOUNT) == b"same"
    with pytest.raises(common.ReleaseError):
        common.put_content(s3, "fixture-artifacts", "objects/a", b"different", ACCOUNT)
    assert all(kw["ExpectedBucketOwner"] == ACCOUNT for _, kw in s3.calls)


@pytest.mark.parametrize("version", [None, "", "null"])
def test_unversioned_references_refused(version):
    with pytest.raises(common.ReleaseError):
        common.s3_location({"uri": "s3://fixture-artifacts/key", "versionId": version})


def test_private_records_never_world_readable(tmp_path):
    path = tmp_path / "private.json"
    common.write(path, {"fixture": True})
    assert path.stat().st_mode & 0o777 == 0o600


def test_sdk_s3_upload_parameters_are_valid():
    client = boto3.client("s3", region_name=REGION, aws_access_key_id="fixture", aws_secret_access_key="fixture")
    data = b"fixture"
    with Stubber(client) as stub:
        stub.add_response("put_object", {"VersionId": "version"}, {"Bucket": "fixture-artifacts", "Key": "key", "Body": data,
                          "ExpectedBucketOwner": ACCOUNT, "ServerSideEncryption": "AES256", "ChecksumSHA256": base64.b64encode(bytes.fromhex(common.sha(data))).decode(),
                          "Metadata": {"sha256": common.sha(data)}, "IfNoneMatch": "*"})
        assert common.put_bytes(client, "fixture-artifacts", "key", data, ACCOUNT, IfNoneMatch="*")["versionId"] == "version"
        stub.assert_no_pending_responses()


def test_iam_pagination_uses_marker_not_nexttoken():
    client = boto3.client("iam", region_name=REGION, aws_access_key_id="fixture", aws_secret_access_key="fixture")
    with Stubber(client) as stub:
        stub.add_response("list_role_policies", {"PolicyNames": ["one"], "IsTruncated": True, "Marker": "next"}, {"RoleName": "fixture"})
        stub.add_response("list_role_policies", {"PolicyNames": ["two"], "IsTruncated": False}, {"RoleName": "fixture", "Marker": "next"})
        assert common.pages(client, "list_role_policies", "PolicyNames", RoleName="fixture") == ["one", "two"]


@pytest.mark.parametrize("selected,retained,expected", [
    ({"frontend"}, {}, {"frontend"}),
    ({"database"}, {}, {"database"}),
    ({"backend"}, {}, {"backend", "infrastructure", "database"}),
    ({"infrastructure"}, {}, {"backend", "infrastructure", "database"}),
    ({"infrastructure"}, {"backend": {}, "database": {}}, {"infrastructure"}),
    ({"backend"}, {"backend": {}, "database": {}}, {"backend", "infrastructure"}),
])
def test_build_dependency_closure(selected, retained, expected):
    assert build.dependency_closure(selected, {"components": retained}) == expected


def test_build_cache_builds_only_once_and_keeps_unchanged_artifacts(monkeypatch, tmp_path):
    s3 = MemoryS3()
    built, checked = [], []
    monkeypatch.setattr(build.common.planner, "input_hash", lambda *args: "c" * 64)
    monkeypatch.setattr(build, "verify_artifact", lambda *args: None)
    monkeypatch.setattr(build, "build_image", lambda name, *args: built.append(name) or artifact(name))
    first, stages = build.build_manifest(session(s3), tmp_path, REVISION, {"frontend"}, None, "fixture-artifacts", ACCOUNT, REGION, tmp_path,
                                         lambda name, *_: checked.append(name))
    second, stages2 = build.build_manifest(session(s3), tmp_path, REVISION, {"frontend"}, first, "fixture-artifacts", ACCOUNT, REGION, tmp_path,
                                           lambda name, *_: checked.append(name))
    assert first["components"] == second["components"]
    assert built == ["frontend"] and checked == ["frontend"]
    assert stages2 == [{"component": "frontend", "action": "reused-built-artifact"}]
    assert not any("build-locks/" in key for _, key in s3.objects)


def test_backend_updates_template_binding_without_database_rebuild(monkeypatch, tmp_path):
    s3 = MemoryS3()
    calls = []
    previous = manifest(database=artifact("database"))
    monkeypatch.setattr(build.common.planner, "input_hash", lambda *args: "c" * 64)
    monkeypatch.setattr(build, "verify_artifact", lambda *args: None)
    monkeypatch.setattr(build, "build_backend", lambda *args: (calls.append("backend") or b"zip", {}))
    def templates(source, backend, *args):
        assert backend["uri"].startswith("s3://") and backend["versionId"]
        calls.append("templates")
        return b"template-bundle", {}
    monkeypatch.setattr(build, "publish_templates", templates)
    result, _ = build.build_manifest(session(s3), tmp_path, REVISION, {"backend"}, previous, "fixture-artifacts", ACCOUNT, REGION, tmp_path, lambda *a: None)
    assert calls == ["backend", "templates"]
    assert result["components"]["database"] == previous["components"]["database"]
    assert result["components"]["infrastructure"]["dependencies"]["backend"]["versionId"]


def test_failed_validation_publishes_no_build_receipt_and_releases_only_its_lock(monkeypatch, tmp_path):
    s3 = MemoryS3()
    monkeypatch.setattr(build.common.planner, "input_hash", lambda *args: "c" * 64)
    monkeypatch.setattr(build, "build_image", lambda *args: pytest.fail("No build after failed checks"))
    def fail(*args): common.require(False, "fixture validation failed")
    with pytest.raises(common.ReleaseError, match="validation failed"):
        build.build_manifest(session(s3), tmp_path, REVISION, {"frontend"}, None, "fixture-artifacts", ACCOUNT, REGION, tmp_path, fail)
    assert not s3.objects


def test_unknown_validation_never_silently_skipped(tmp_path):
    with pytest.raises(common.ReleaseError, match="Unknown selected validation"):
        build.validations("unknown", tmp_path, tmp_path)


class Connection:
    def __init__(self, db=common.DEV_DATABASE, applied=None):
        self.db, self.applied, self.statements = db, applied or {}, []
        self.rows = []
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, args=None):
        self.statements.append(sql)
        if "current_database" in sql: self.rows = [(self.db,)]
        elif "to_regclass" in sql: self.rows = [("platform.schema_migrations",)]
        elif sql.startswith("SELECT name"): self.rows = list(self.applied.items())
        elif sql.startswith("INSERT INTO"): self.applied[args[0]] = args[1]
        return self
    def fetchone(self): return self.rows[0]
    def fetchall(self): return self.rows


def sql_bundle(tmp_path):
    path = tmp_path / "database/migrations"
    path.mkdir(parents=True)
    (path / "001_fixture.sql").write_text("SELECT 1;")
    return database.bundle(tmp_path)


def test_sql_apply_once_checks_history_and_dev_identity(monkeypatch, tmp_path):
    content = sql_bundle(tmp_path)
    conn = Connection()
    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda *a: conn)
    assert database.inspect("private-dsn", content) == ["001_fixture.sql"]
    assert conn.statements[0] == "SET TRANSACTION READ ONLY"
    assert database.apply("private-dsn", content, ["001_fixture.sql"]) == ["001_fixture.sql"]
    assert database.apply("private-dsn", content, []) == []
    assert conn.statements.count("SELECT 1;") == 1
    conn.applied["001_fixture.sql"] = "modified"
    with pytest.raises(common.ReleaseError, match="checksum"):
        database.inspect("private-dsn", content)


@pytest.mark.parametrize("db", ["navigan", "postgres", "navigan_test"])
def test_live_sql_rejects_any_other_database(db):
    conn = Connection(db)
    with pytest.raises(common.ReleaseError, match="not the DEV"):
        database.inventory(conn, {"001_fixture.sql": "SELECT 1;"})
    assert len(conn.statements) == 1


def test_migration_removal_and_stale_pending_rejected(monkeypatch, tmp_path):
    content = sql_bundle(tmp_path)
    conn = Connection(applied={"missing.sql": "x"})
    with pytest.raises(common.ReleaseError, match="removal"):
        database.inventory(conn, {})
    conn.applied = {}
    import psycopg
    monkeypatch.setattr(psycopg, "connect", lambda *a: conn)
    with pytest.raises(common.ReleaseError, match="history changed"):
        database.apply("private-dsn", content, [])
    assert "SELECT 1;" not in conn.statements


@pytest.mark.parametrize("field,value", [("environment", "prod"), ("stack", "navigan-custmanagement-cfnstk"),
    ("database", "navigan"), ("apiOrigin", "https://api.navigan.click"), ("apiBasePath", "/v1/api/v1")])
def test_dev_configuration_rejects_prod_and_wrong_bindings(field, value):
    value_config = config()
    value_config[field] = value
    with pytest.raises(common.ReleaseError): target.validate_config(value_config)


def test_preview_port_and_public_allowlist():
    value = config()
    target.validate_config(value)
    value["frontend"]["port"] = 3000
    with pytest.raises(common.ReleaseError): target.validate_config(value)
    value["frontend"]["port"] = 3001
    value["frontend"]["publicEnvironment"]["DATABASE_PASSWORD"] = "private"
    with pytest.raises(common.ReleaseError): target.validate_config(value)


def test_config_only_release_reuses_artifact_identity():
    value = manifest(frontend=artifact("frontend"))
    cfg = config()
    previous = {"manifest": value, "configuration": copy.deepcopy(cfg), "configurationHash": "old"}
    cfg["frontend"]["publicEnvironment"]["NAVIGAN_PUBLIC_CORPORATE_LOGO_URL"] = "/new-logo.svg"
    assert deploy.selected_components(value, previous, "new", cfg) == {"frontend"}
    previous["configuration"] = copy.deepcopy(cfg)
    cfg["parameterOverrides"] = {"LogLevel": "INFO"}
    assert deploy.selected_components(value, previous, "new", cfg) == {"infrastructure"}


def test_noop_metadata_and_unsupported_deployment_components():
    value = manifest(frontend=artifact("frontend"))
    previous = {"manifest": value, "configurationHash": "same"}
    candidate = copy.deepcopy(value)
    candidate["components"]["frontend"]["builtAt"] = "different metadata"
    assert deploy.selected_components(candidate, previous, "same") == set()
    with pytest.raises(common.ReleaseError, match="remove"):
        deploy.selected_components(manifest(), previous, "same")
    with pytest.raises(common.ReleaseError, match="isolated DEV"):
        deploy.selected_components(manifest(**{"tools-gateway": artifact("tools-gateway")}), None, "same")


def change(kind="AWS::Lambda::Function", action="Modify", replacement="False", name="Function", **extra):
    return {"ResourceChange": {"ResourceType": kind, "LogicalResourceId": name, "Action": action, "Replacement": replacement, **extra}}


class Cloud:
    def __init__(self, rows, stack=STACK): self.rows, self.stack = rows, stack
    def describe_change_set(self, **kw):
        return {"StackId": self.stack, "Changes": self.rows}


@pytest.mark.parametrize("row", [change(), change("AWS::IAM::Policy", "Add"), change("AWS::CloudFormation::Stack")])
def test_scope_allows_owned_in_place_application_changes(row):
    rows, blocked = deploy.inspect_changes(Cloud([row]), "plan", STACK)
    assert rows and not blocked


@pytest.mark.parametrize("row", [change(action="Remove"), change(replacement="True"), change("AWS::RDS::DBInstance"),
    change("AWS::ApiGatewayV2::Api"), change("AWS::S3::Bucket", "Add"), change("AWS::Lambda::Permission", replacement="Conditional")])
def test_scope_blocks_destructive_or_unproven_changes(row):
    assert deploy.inspect_changes(Cloud([row]), "plan", STACK)[1]


def test_scope_rejects_foreign_stack_even_with_similar_changes():
    with pytest.raises(common.ReleaseError, match="ownership"):
        deploy.inspect_changes(Cloud([change()], STACK.replace(common.DEV_STACK, "prod")), "plan", STACK)


def test_dynamic_binding_proof_requires_same_native_definition_and_unchanged_dependencies():
    template = {"Resources": {"Function": {"Type": "AWS::Lambda::Function"}, "Permission": {
        "Type": "AWS::Lambda::Permission", "Properties": {"FunctionName": {"Fn::GetAtt": ["Function", "Arn"]}, "Principal": "events.amazonaws.com"}}}}
    rows = [change(), change("AWS::Lambda::Permission", replacement="Conditional", name="Permission", Details=[{"Evaluation": "Dynamic"}])]
    cfn = Cloud(rows)
    cfn.get_template = lambda **kw: {"TemplateBody": template}
    state = {"stacks": {"root": {"stack": {"StackId": STACK}, "processed": copy.deepcopy(template)}}}
    result, blocked = deploy.inspect_changes(cfn, "plan", STACK, state=state)
    assert not blocked and result[1]["unchangedBindingProof"]
    template["Resources"]["Permission"]["Properties"]["Principal"] = "*"
    assert deploy.inspect_changes(cfn, "plan", STACK, state=state)[1]


def test_scope_worker_allows_only_task_and_in_place_service():
    assert not deploy.inspect_changes(Cloud([change("AWS::ECS::TaskDefinition", replacement="True", name="WorkerTask")]), "plan", STACK, worker=True)[1]
    assert deploy.inspect_changes(Cloud([change("AWS::IAM::Role")]), "plan", STACK, worker=True)[1]


def test_wait_does_not_mistake_previous_update_complete_for_new_completion(monkeypatch):
    executions = iter(["AVAILABLE", "EXECUTE_IN_PROGRESS", "EXECUTE_COMPLETE"])
    calls = []
    cfn = SimpleNamespace(describe_stacks=lambda **kw: {"Stacks": [{"StackStatus": "UPDATE_COMPLETE"}]},
                          describe_change_set=lambda **kw: {"ExecutionStatus": next(executions)})
    monkeypatch.setattr(deploy.time, "sleep", lambda seconds: calls.append(seconds))
    deploy.wait_stack(cfn, STACK, "plan")
    assert calls == [5, 5]


def test_deployment_lock_is_exclusive_and_old_unlock_cannot_remove_new_owner():
    s3 = MemoryS3()
    sess = session(s3)
    plan = {"config": config(), "id": "a" * 32}
    first = deploy.lock(sess, plan)
    with pytest.raises(ClientError): deploy.lock(sess, plan)
    deploy.unlock(sess, plan, first)
    second = deploy.lock(sess, {**plan, "id": "b" * 32})
    deploy.unlock(sess, plan, first)
    assert common.object_bytes(s3, second, ACCOUNT)


def test_native_rollback_preserves_actual_lambda_configuration():
    old = {"Role": {"Fn::GetAtt": ["Role", "Arn"]}, "Environment": {"Variables": {"STALE": "value"}}, "Layers": ["stale"], "VpcConfig": {"SubnetIds": ["stale"]}}
    cfg = {"Role": "arn:aws:iam::123456789012:role/dev", "Runtime": "python3.12", "Handler": "app.handler", "MemorySize": 1024,
           "Timeout": 30, "Environment": {"Variables": {"LIVE": "retained"}}, "VpcConfig": {"VpcId": "vpc-dev", "SubnetIds": ["subnet-dev"], "SecurityGroupIds": ["sg-dev"]},
           "Layers": [{"Arn": "arn:aws:lambda:ap-south-1:123456789012:layer:dev:3"}], "Architectures": ["x86_64"]}
    result = target.function_properties(old, cfg, artifact())
    assert result["Environment"] == cfg["Environment"]
    assert "VpcId" not in result["VpcConfig"] and result["VpcConfig"]["SubnetIds"] == ["subnet-dev"]
    assert result["Layers"] == [cfg["Layers"][0]["Arn"]]
    assert result["Role"] == old["Role"] and result["Code"]["S3ObjectVersion"] == "1"
    assert old["Environment"]["Variables"] == {"STALE": "value"}


def test_plan_is_bound_to_immutable_remote_bytes(monkeypatch, tmp_path):
    cfg = config()
    plan = {"format": deploy.FORMAT, "id": "a" * 32, "config": cfg, "manifest": manifest(),
            "configurationHash": common.sha(common.canonical(cfg)), "manifestHash": common.sha(common.canonical(manifest()))}
    s3 = MemoryS3()
    ref = common.put_bytes(s3, cfg["artifactBucket"], "plan.json", common.canonical(plan), ACCOUNT)
    path = tmp_path / "release-plan.json"
    common.write(path, plan)
    common.write(tmp_path / "plan-reference.json", ref)
    monkeypatch.setattr(common, "verify_registry", lambda *args: None)
    assert deploy.load_plan(session(s3), path) == plan
    plan["config"]["parameterOverrides"]["Anything"] = "edited"
    common.write(path, plan)
    with pytest.raises(common.ReleaseError, match="immutable"):
        deploy.load_plan(session(s3), path)


def test_local_rollback_capture_is_bound_to_the_remote_plan(monkeypatch, tmp_path):
    cfg = config()
    common.write(tmp_path / "baseline.json", {"working": "code"})
    plan = {"format": deploy.FORMAT, "id": "a" * 32, "config": cfg, "manifest": manifest(),
            "configurationHash": common.sha(common.canonical(cfg)), "manifestHash": common.sha(common.canonical(manifest())),
            "captureHashes": {"baseline.json": common.sha(common.canonical({"working": "code"}))}}
    s3 = MemoryS3()
    ref = common.put_bytes(s3, cfg["artifactBucket"], "plan.json", common.canonical(plan), ACCOUNT)
    path = tmp_path / "release-plan.json"
    common.write(path, plan)
    common.write(tmp_path / "plan-reference.json", ref)
    monkeypatch.setattr(common, "verify_registry", lambda *args: None)
    assert deploy.load_plan(session(s3), path) == plan
    common.write(tmp_path / "baseline.json", {"working": "edited"})
    with pytest.raises(common.ReleaseError, match="capture differs"):
        deploy.load_plan(session(s3), path)


def test_failed_verification_never_records_success(monkeypatch, tmp_path):
    plan = {"config": config(), "id": "a" * 32, "selected": [], "manifest": manifest(), "cloudPlans": [], "databaseRequired": False}
    common.write(tmp_path / "execution.json", {"planId": plan["id"]})
    common.write(tmp_path / "baseline.json", {"stacks": {}})
    common.write(tmp_path / "previous-record.json", None)
    monkeypatch.setattr(deploy, "load_plan", lambda *args: plan)
    monkeypatch.setattr(target, "snapshot", lambda *args: {"stacks": {}})
    monkeypatch.setattr(deploy, "verify_target_manifest", lambda *args, **kw: None)
    monkeypatch.setattr(deploy, "smoke", lambda *args, **kw: common.require(False, "fixture auth failed"))
    s3 = MemoryS3()
    with pytest.raises(common.ReleaseError, match="auth failed"):
        deploy.verify(session(s3), tmp_path / "release-plan.json", token="fixture")
    assert not s3.calls


def test_success_record_is_conditional_and_after_authenticated_checks(monkeypatch, tmp_path):
    cfg = config()
    plan = {"config": cfg, "id": "a" * 32, "selected": [], "manifest": manifest(), "cloudPlans": [], "databaseRequired": False,
            "configurationHash": "fixture", "previousEtag": None}
    s3 = MemoryS3()
    reference = deploy.lock(session(s3), plan)
    common.write(tmp_path / "execution.json", {"planId": plan["id"], "lock": reference})
    common.write(tmp_path / "baseline.json", {"stacks": {}})
    common.write(tmp_path / "previous-record.json", None)
    monkeypatch.setattr(deploy, "load_plan", lambda *args: plan)
    monkeypatch.setattr(target, "snapshot", lambda *args: {"stacks": {}})
    monkeypatch.setattr(target, "stamp", lambda *args: "fixture")
    monkeypatch.setattr(deploy, "verify_target_manifest", lambda *args, **kw: None)
    checked = []
    monkeypatch.setattr(deploy, "smoke", lambda *args, **kw: checked.append("authenticated") or [{"status": 200}])
    deploy.verify(session(s3), tmp_path / "release-plan.json", token="fixture")
    assert checked == ["authenticated"]
    result = common.get_optional(s3, cfg["artifactBucket"], deploy.CURRENT, ACCOUNT)[0]
    assert result["status"] == "SUCCEEDED"
    put = next(kw for name, kw in s3.calls if name == "put" and kw["Key"] == deploy.CURRENT)
    assert put["IfNoneMatch"] == "*"
    assert common.read(tmp_path / "execution.json")["lockReleased"]


def test_execute_cannot_be_repeated(monkeypatch, tmp_path):
    common.write(tmp_path / "execution.json", {})
    monkeypatch.setattr(deploy, "load_plan", lambda *args: {"blocked": []})
    with pytest.raises(common.ReleaseError, match="already requested"):
        deploy.execute(None, tmp_path / "release-plan.json")


def test_deployer_does_not_invoke_build_commands():
    source = (common.ROOT / "scripts/deploy-release-dev.py").read_text()
    assert '"docker", "build"' not in source and '"sam", "build"' not in source
    assert "builder.build_manifest(" not in source and "builder.build_image(" not in source


def test_artifact_foundation_owns_only_registry_resources():
    document = common.yaml_document((common.ROOT / "infrastructure/companion/dev-release-artifacts.yaml").read_text())
    assert {item["Type"] for item in document["Resources"].values()} == {"AWS::S3::Bucket", "AWS::S3::BucketPolicy", "AWS::ECR::Repository"}
    assert document["Resources"]["Artifacts"]["Properties"]["VersioningConfiguration"]["Status"] == "Enabled"
    repos = [item for item in document["Resources"].values() if item["Type"] == "AWS::ECR::Repository"]
    assert len(repos) == 6 and all(item["Properties"]["ImageTagMutability"] == "IMMUTABLE" for item in repos)


def test_public_runtime_verification_checks_all_bindings():
    cfg = config()
    value = {"oidcAuthority": "", "oidcClientId": "devclient", "appUrl": "http://localhost:3001", "corporateLogoUrl": "",
             "migrationConnectorApiBaseUrl": "", "migrationConnectorImageRepository": "", "migrationConnectorImageDigest": "", "migrationUiPreview": False}
    deploy.verify_frontend_runtime(cfg, value)
    value["appUrl"] = "https://prod.example.invalid"
    with pytest.raises(common.ReleaseError): deploy.verify_frontend_runtime(cfg, value)


def test_native_getatt_spellings_are_equivalent_without_changing_other_values():
    assert common.native_form({"Fn::GetAtt": "Shared.Outputs.Api"}) == {"Fn::GetAtt": ["Shared", "Outputs.Api"]}
    assert common.native_form({"Ref": "Shared.Outputs.Api"}) == {"Ref": "Shared.Outputs.Api"}


def rollback_fixture(monkeypatch, tmp_path):
    cfg = config()
    plan = {"id": "a" * 32, "config": cfg, "rootNeeded": False, "selected": [], "previousEtag": None,
            "manifest": manifest(database=artifact("database"))}
    s3 = MemoryS3()
    journal = {"planId": plan["id"], "completedStages": ["database"], "lock": deploy.lock(session(s3), plan)}
    common.write(tmp_path / "execution.json", journal)
    common.write(tmp_path / "previous-record.json", None)
    monkeypatch.setattr(deploy, "load_plan", lambda *args: plan)
    monkeypatch.setattr(target, "snapshot", lambda *args: {"stacks": {"root": {"stack": {"StackId": STACK}}}})
    monkeypatch.setattr(deploy, "token_value", lambda: "fixture")
    monkeypatch.setattr(deploy, "smoke", lambda *args, **kw: [{"status": 200}])
    return plan, s3, tmp_path / "release-plan.json"


def test_first_release_rollback_records_restored_baseline_and_retains_forward_schema(monkeypatch, tmp_path):
    plan, s3, path = rollback_fixture(monkeypatch, tmp_path)
    deploy.rollback(session(s3), path)
    current = common.get_optional(s3, config()["artifactBucket"], deploy.CURRENT, ACCOUNT)[0]
    assert current["status"] == "BASELINE_RESTORED"
    assert current["forwardDatabaseArtifact"] == plan["manifest"]["components"]["database"]
    assert common.read(tmp_path / "execution.json")["rollbackComplete"]
    with pytest.raises(common.ReleaseError, match="already completed"):
        deploy.rollback(session(s3), path)


def test_rollback_cannot_overwrite_a_newer_successful_release(monkeypatch, tmp_path):
    plan, s3, path = rollback_fixture(monkeypatch, tmp_path)
    common.put_bytes(s3, config()["artifactBucket"], deploy.CURRENT, common.canonical({"planId": "newer"}), ACCOUNT)
    with pytest.raises(common.ReleaseError, match="Last-successful record changed"):
        deploy.rollback(session(s3), path)
    assert common.get_optional(s3, config()["artifactBucket"], deploy.CURRENT, ACCOUNT)[0]["planId"] == "newer"


def test_interrupted_rollback_record_publication_is_adopted_without_repeating_write(monkeypatch, tmp_path):
    plan, s3, path = rollback_fixture(monkeypatch, tmp_path)
    deploy.rollback(session(s3), path)
    journal = common.read(tmp_path / "execution.json")
    journal.pop("rollbackComplete")
    journal.pop("rollbackRecordPublished")
    common.write(tmp_path / "execution.json", journal)
    before = s3.next_version
    deploy.rollback(session(s3), path)
    assert s3.next_version == before


def test_failed_authenticated_rollback_does_not_publish_a_restored_record(monkeypatch, tmp_path):
    _, s3, path = rollback_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(deploy, "smoke", lambda *args, **kw: common.require(False, "read failed"))
    with pytest.raises(common.ReleaseError, match="read failed"):
        deploy.rollback(session(s3), path)
    assert common.get_optional(s3, config()["artifactBucket"], deploy.CURRENT, ACCOUNT) is None


def test_production_is_not_a_workflow_or_runner_action():
    text = (common.ROOT / ".github/workflows/dev-release.yml").read_text()
    assert "environment: dev" in text and "cancel-in-progress: false" in text
    assert "pull_request:" not in text and "environment: prod" not in text
    assert "upload-artifact" not in text
    runner = (common.ROOT / "scripts/run-dev-release.py").read_text()
    assert '"prod"' not in runner


def test_default_deployment_never_requests_a_browser_token(monkeypatch):
    monkeypatch.delenv("NAVIGAN_DEV_SMOKE_TOKEN", raising=False)
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("No interactive credential collection"))
    monkeypatch.setattr(deploy.builder, "http", lambda *args, **kw: pytest.fail("No unauthenticated calls to protected summary APIs"))
    assert deploy.token_value() is None
    assert deploy.smoke(config(), None) == []
    assert deploy.smoke(config(), None, frontend=True) == []


def test_optional_token_is_validated_and_bearer_prefix_normalized(monkeypatch):
    monkeypatch.setenv("NAVIGAN_DEV_SMOKE_TOKEN", "Bearer fixture.access.token")
    assert deploy.token_value() == "fixture.access.token"
    monkeypatch.setenv("NAVIGAN_DEV_SMOKE_TOKEN", "invalid\nheader")
    with pytest.raises(common.ReleaseError, match="format"):
        deploy.token_value()


def test_supplied_token_still_runs_all_authenticated_smoke_checks(monkeypatch):
    calls = []
    def http(url, **kw):
        calls.append((url, kw))
        return common.canonical({"total": 0, "byStatus": {}, "byProvider": {}})
    monkeypatch.setattr(deploy.builder, "http", http)
    assert len(deploy.smoke(config(), "fixture")) == 3
    assert all(kw == {"token": "fixture"} for _, kw in calls)


def test_optional_auth_does_not_bypass_frontend_health_checks(monkeypatch, tmp_path):
    cfg = config()
    image = artifact("frontend")
    plan = {"config": cfg, "id": "a" * 32, "selected": ["frontend"], "manifest": manifest(frontend=image), "cloudPlans": [], "databaseRequired": False}
    common.write(tmp_path / "execution.json", {"planId": plan["id"], "frontend": {"container": "fixture", "image": image["uri"]}})
    common.write(tmp_path / "baseline.json", {"stacks": {}})
    common.write(tmp_path / "previous-record.json", None)
    monkeypatch.setattr(deploy, "load_plan", lambda *args: plan)
    monkeypatch.setattr(target, "snapshot", lambda *args: {"stacks": {}})
    monkeypatch.setattr(deploy, "verify_target_manifest", lambda *args, **kw: None)
    monkeypatch.setattr(deploy.subprocess, "check_output", lambda *args: common.canonical([{"State": {"Running": True}, "Config": {"Image": image["uri"]}}]))
    monkeypatch.setattr(deploy, "verify_frontend_runtime", lambda *args: None)
    def http(url, **kw):
        if url.endswith("/healthz"):
            raise common.ReleaseError("frontend health failed")
        return b"{}"
    monkeypatch.setattr(deploy.builder, "http", http)
    s3 = MemoryS3()
    with pytest.raises(common.ReleaseError, match="frontend health failed"):
        deploy.verify(session(s3), tmp_path / "release-plan.json")
    assert not s3.calls


def test_default_verification_records_auth_as_not_requested(monkeypatch, tmp_path):
    cfg = config()
    plan = {"config": cfg, "id": "a" * 32, "selected": [], "manifest": manifest(), "cloudPlans": [], "databaseRequired": False,
            "configurationHash": "fixture", "previousEtag": None}
    s3 = MemoryS3()
    reference = deploy.lock(session(s3), plan)
    common.write(tmp_path / "execution.json", {"planId": plan["id"], "lock": reference})
    common.write(tmp_path / "baseline.json", {"stacks": {}})
    common.write(tmp_path / "previous-record.json", None)
    monkeypatch.delenv("NAVIGAN_DEV_SMOKE_TOKEN", raising=False)
    monkeypatch.setattr(deploy, "load_plan", lambda *args: plan)
    monkeypatch.setattr(target, "snapshot", lambda *args: {"stacks": {}})
    monkeypatch.setattr(target, "stamp", lambda *args: "fixture")
    monkeypatch.setattr(deploy, "verify_target_manifest", lambda *args, **kw: None)
    monkeypatch.setattr(deploy.builder, "http", lambda *args, **kw: pytest.fail("No token required"))
    deploy.verify(session(s3), tmp_path / "release-plan.json")
    result = common.get_optional(s3, cfg["artifactBucket"], deploy.CURRENT, ACCOUNT)[0]
    assert result["status"] == "SUCCEEDED" and result["authenticatedAcceptance"] == "NOT_REQUESTED"
    assert result["authenticatedChecks"] == []
