"""Checks for the guarded DEV-only source connector delivery workflow."""

import ast
import importlib.util
import io
import json
from pathlib import Path
import shlex
import tomllib
import unittest
from unittest import mock


ROOT = Path(__file__).parents[1]
PIN_SCRIPT = ROOT / "scripts" / "pin_source_connector_dev.py"
spec = importlib.util.spec_from_file_location("pin_source_connector_dev", PIN_SCRIPT)
pin_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin_module)
SCOPED_SCRIPT = ROOT / "scripts" / "source_connector_scoped_change.py"
scoped_spec = importlib.util.spec_from_file_location("source_connector_scoped_change", SCOPED_SCRIPT)
scoped_module = importlib.util.module_from_spec(scoped_spec)
scoped_spec.loader.exec_module(scoped_module)
PATCH_SCRIPT = ROOT / "scripts" / "patch_migration_nested_template.py"
patch_spec = importlib.util.spec_from_file_location("patch_migration_nested_template", PATCH_SCRIPT)
patch_module = importlib.util.module_from_spec(patch_spec)
patch_spec.loader.exec_module(patch_module)

REPOSITORY = (
    "905418045935.dkr.ecr.ap-south-1.amazonaws.com/"
    "navigan/migration-source-connector"
)
DIGEST = "sha256:" + "a" * 64


def parse_parameters(config, environment):
    tokens = shlex.split(config[environment]["deploy"]["parameters"]["parameter_overrides"])
    return dict(token.split("=", 1) for token in tokens)


class DevConnectorReleaseTests(unittest.TestCase):
    def test_deployed_template_patch_does_not_change_other_capabilities(self):
        old_url = (
            "https://s3.ap-south-1.amazonaws.com/"
            "aws-sam-cli-managed-default-samclisourcebucket-xj9yzigmdgri/old.template"
        )
        new_url = old_url.replace("old.template", "new.template")
        root = {"TemplateBody": {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Parameters": {"SomeParameter": {"Type": "String"}},
            "Resources": {
                "ClusterManagement": {"Type": "AWS::CloudFormation::Stack",
                                      "Properties": {"TemplateURL": "https://unchanged/cluster"}},
                "MigrationManagement": {
                    "Type": "AWS::CloudFormation::Stack",
                    "Properties": {"TemplateURL": old_url, "Parameters": {
                        "JwtScope": {"Ref": "JwtScope"}}}},
            },
        }}
        import copy
        snapshot = copy.deepcopy(root)
        result = patch_module.patch_template(
            root, new_url, REPOSITORY, DIGEST,
            "arn:aws:iam::905418045935:role/NaviganSourceConnectorDeliveryRole",
        )
        self.assertEqual(root, snapshot)
        self.assertEqual(result["Resources"]["ClusterManagement"],
                         root["TemplateBody"]["Resources"]["ClusterManagement"])
        self.assertEqual(result["Parameters"],
                         root["TemplateBody"]["Parameters"])
        migration = result["Resources"]["MigrationManagement"]
        self.assertEqual(migration["Properties"]["TemplateURL"], new_url)
        self.assertEqual(migration["Properties"]["Parameters"]["JwtScope"],
                         {"Ref": "JwtScope"})
        self.assertEqual(migration["Properties"]["Parameters"]["MigrationConnectorImageDigest"],
                         DIGEST)

        with self.assertRaises(ValueError):
            patch_module.patch_template(root, old_url, REPOSITORY, DIGEST,
                                        "arn:aws:iam::905418045935:role/NaviganSourceConnectorDeliveryRole")
        with self.assertRaises(ValueError):
            patch_module.patch_template({"TemplateBody": "old YAML"}, new_url,
                                        REPOSITORY, DIGEST,
                                        "arn:aws:iam::905418045935:role/NaviganSourceConnectorDeliveryRole")

    def test_stage_script_creates_nested_preview_but_never_executes(self):
        script = (ROOT / "scripts" / "stage-migration-source-connector-dev.sh").read_text()
        self.assertIn('DEV_STACK="navigan-ashok-dev"', script)
        self.assertIn('ACCOUNT="905418045935"', script)
        self.assertIn('"new_migration_approach_18oct26"', script)
        self.assertIn('git -C "$ROOT" archive HEAD', script)
        self.assertIn('ls-remote --exit-code origin refs/heads/new_migration_approach_18oct26', script)
        self.assertNotIn('rev-parse origin/new_migration_approach_18oct26', script)
        self.assertIn('--template-stage Processed', script)
        self.assertIn('patch_migration_nested_template.py', script)
        self.assertIn('--include-nested-stacks', script)
        self.assertIn('source_connector_scoped_change.py" verify', script)
        self.assertNotIn('execute-change-set', script)
        self.assertNotIn('sam deploy', script)

    def test_preserve_all_existing_root_stack_parameters(self):
        original = [
            {"ParameterKey": "JwtScope", "ParameterValue": "navigan/api"},
            {"ParameterKey": "SourceConnectorDeliveryRoleArn", "ParameterValue": "role"},
        ]
        self.assertEqual(scoped_module.preserve_parameters(original), [
            {"ParameterKey": "JwtScope", "UsePreviousValue": True},
            {"ParameterKey": "SourceConnectorDeliveryRoleArn", "UsePreviousValue": True},
        ])
        with self.assertRaises(ValueError):
            scoped_module.preserve_parameters([])

    def test_scoped_update_preserves_all_other_stack_parameters(self):
        source = [
            {"ParameterKey": "DatabaseName", "ParameterValue": "dev-db"},
            {"ParameterKey": "ApiDatabaseSecretArn", "ParameterValue": "sensitive-ref"},
            {"ParameterKey": "MigrationConnectorImageRepository", "ParameterValue": ""},
            {"ParameterKey": "MigrationConnectorImageDigest", "ParameterValue": ""},
        ]
        output = scoped_module.prepare_parameters(source, REPOSITORY, DIGEST)
        self.assertEqual(output, [
            {"ParameterKey": "DatabaseName", "UsePreviousValue": True},
            {"ParameterKey": "ApiDatabaseSecretArn", "UsePreviousValue": True},
            {"ParameterKey": "MigrationConnectorImageRepository", "ParameterValue": REPOSITORY},
            {"ParameterKey": "MigrationConnectorImageDigest", "ParameterValue": DIGEST},
        ])

    def test_scoped_update_rejects_missing_or_duplicate_image_parameters(self):
        with self.assertRaises(ValueError):
            scoped_module.prepare_parameters(
                [{"ParameterKey": "MigrationConnectorImageRepository"}], REPOSITORY, DIGEST
            )
        with self.assertRaises(ValueError):
            scoped_module.prepare_parameters(
                [{"ParameterKey": "MigrationConnectorImageRepository"}] * 2 +
                [{"ParameterKey": "MigrationConnectorImageDigest"}], REPOSITORY, DIGEST
            )

    def test_change_set_must_only_modify_existing_migration_nested_stack(self):
        allowed = {
            "Status": "CREATE_COMPLETE",
            "Changes": [{"ResourceChange": {
                "LogicalResourceId": "MigrationManagement",
                "ResourceType": "AWS::CloudFormation::Stack",
                "Action": "Modify",
                "Replacement": "False",
            }}],
        }
        scoped_module.ensure_migration_only(allowed)
        rejected = [
            {**allowed, "Status": "FAILED"},
            {**allowed, "Changes": []},
            {**allowed, "Changes": allowed["Changes"] * 2},
            {**allowed, "Changes": [{"ResourceChange": {
                **allowed["Changes"][0]["ResourceChange"],
                "LogicalResourceId": "ClusterManagement",
            }}]},
            {**allowed, "Changes": [{"ResourceChange": {
                **allowed["Changes"][0]["ResourceChange"],
                "Replacement": "True",
            }}]},
        ]
        for case in rejected:
            with self.subTest(case=case), self.assertRaises(ValueError):
                scoped_module.ensure_migration_only(case)

    def test_scoped_release_has_strict_dev_and_change_set_guards(self):
        script = (ROOT / "scripts" / "activate-migration-source-connector-dev.sh").read_text()
        self.assertIn('EXPECTED_ACCOUNT="905418045935"', script)
        self.assertIn('DEV_STACK="navigan-ashok-dev"', script)
        self.assertIn('"new_migration_approach_18oct26"', script)
        self.assertIn('--use-previous-template', script)
        self.assertIn('source_connector_scoped_change.py" verify', script)
        self.assertIn('Execute this MigrationManagement-only DEV change set?', script)
        self.assertIn('aws cloudformation execute-change-set', script)
        self.assertNotIn('sam deploy', script)
        self.assertNotIn('stack-name navigan-frontend', script)

    def test_pinning_preserves_production_and_other_dev_parameters(self):
        before = (ROOT / "samconfig.toml").read_text(encoding="utf-8")
        # Public SAM profiles omit private bindings. Exercise an operator's
        # temporary private configuration with approved synthetic DEV values.
        import re
        parsed_before = tomllib.loads(before)
        for environment in ("default", "dev"):
            pattern = re.compile(r"(?ms)(^\[" + environment + r"\.deploy\.parameters\]\n)(.*?)(?=^\[|\Z)")
            section = pattern.search(before)
            block = section.group(2)
            tokens = parsed_before[environment]["deploy"]["parameters"].get("parameter_overrides", "")
            values = dict(token.split("=", 1) for token in shlex.split(tokens))
            values.update({"DatabaseName": "navigan_dev", "ApiDatabaseSecretArn": "fixture-dev-secret-reference",
                           "SourceConnectorDeliveryRoleArn": "arn:aws:iam::905418045935:role/test-approved-delivery"})
            line = "parameter_overrides = " + json.dumps(" ".join(shlex.quote(key + "=" + value) for key, value in values.items()))
            if re.search(r"(?m)^parameter_overrides\s*=", block):
                block = re.sub(r"(?m)^parameter_overrides\s*=.*$", lambda _: line, block)
            else:
                block += line + "\n"
            before = before[:section.start(2)] + block + before[section.end(2):]
        before_prod = before.split("[prod.validate.parameters]", 1)[1]
        original = tomllib.loads(before)

        after = pin_module.pin_dev_config(before, REPOSITORY, DIGEST)
        self.assertEqual(after.split("[prod.validate.parameters]", 1)[1], before_prod)
        parsed = tomllib.loads(after)

        for environment in ("default", "dev"):
            with self.subTest(environment=environment):
                params = parse_parameters(parsed, environment)
                original_params = parse_parameters(original, environment)
                self.assertEqual(params["MigrationConnectorImageRepository"], REPOSITORY)
                self.assertEqual(params["MigrationConnectorImageDigest"], DIGEST)
                self.assertEqual(
                    params["SourceConnectorDeliveryRoleArn"],
                    parse_parameters(original, "dev")["SourceConnectorDeliveryRoleArn"],
                )
                for name, value in original_params.items():
                    if name not in {"SourceConnectorDeliveryRoleArn", "MigrationConnectorImageRepository", "MigrationConnectorImageDigest"}:
                        self.assertEqual(params[name], value)

        self.assertEqual(after, pin_module.pin_dev_config(after, REPOSITORY, DIGEST))

    def test_rejects_incorrect_or_mutable_images(self):
        cases = (
            ("public.ecr.aws/any/image", DIGEST),
            ("905418045935.dkr.ecr.ap-south-1.amazonaws.com/foo", "latest"),
            (REPOSITORY + "@" + DIGEST, DIGEST),
        )
        for repository, digest in cases:
            with self.subTest(repository=repository, digest=digest):
                with self.assertRaises(ValueError):
                    pin_module.pin_dev_config(
                        (ROOT / "samconfig.toml").read_text(encoding="utf-8"),
                        repository,
                        digest,
                    )

    def test_deployment_is_explicit_dev_only_and_uses_correct_image(self):
        script = (ROOT / "scripts" / "deploy-migration-source-connector-dev.sh").read_text()
        self.assertIn('  --deploy-dev)', script)
        self.assertIn('  --resume-dev)', script)
        self.assertIn('^dev-[0-9a-f]{12}-[0-9]{14}$', script)
        self.assertIn('"new_migration_approach_18oct26"', script)
        self.assertIn('EXPECTED_ACCOUNT="905418045935"', script)
        self.assertIn('DEV_STACK="navigan-ashok-dev"', script)
        self.assertIn('git -C "$ROOT" archive HEAD', script)
        self.assertIn('migration_connector/Dockerfile', script)
        self.assertIn('sam deploy --config-env dev', script)
        self.assertIn('PIP_DEFAULT_TIMEOUT', script)
        self.assertIn('PIP_RETRIES', script)
        self.assertIn('sam build --use-container', script)
        self.assertIn('--container-env-var-file', script)
        self.assertIn('--confirm-changeset', script)
        self.assertNotIn('--config-env prod', script)
        self.assertIn('MIGRATION_CONNECTOR_IMAGE_DIGEST', script)

    def test_ssm_installer_can_pull_private_ecr_image_without_logging_credentials(self):
        path = (
            ROOT / "src" / "navigan" / "modules" / "migration_management"
            / "source_connector_installation.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        installer = next(
            statement.value.value
            for statement in tree.body
            if isinstance(statement, ast.Assign)
            and any(getattr(target, "id", "") == "INSTALLER" for target in statement.targets)
        )
        compile(installer, "<ssm bootstrap>", "exec")
        self.assertIn('"get-login-password"', installer)
        self.assertIn('type: kubernetes.io/dockerconfigjson', installer)
        self.assertIn("imagePullSecrets:", installer)
        self.assertIn('stderr=subprocess.PIPE', installer)
        self.assertNotIn('print(ecr_password)', installer)

        bootstrap = {
            "sourceClusterId": "SRC-" + "a" * 32,
            "enrollmentToken": "z" * 43,
            "apiBaseUrl": "https://api.example.test/v1/api/v1",
            "imageRepository": REPOSITORY,
            "imageDigest": DIGEST,
            "kubeconfigPath": "/etc/kubernetes/admin.conf",
        }
        enrollment = {"connectorId": "SCC-" + "b" * 32,
                      "connectorToken": "y" * 43}

        def fake_open(_path, mode="r", **_kwargs):
            return io.StringIO(json.dumps(bootstrap) if "r" in mode else "")

        with (
            mock.patch("builtins.open", side_effect=fake_open),
            mock.patch("sys.argv", ["installer", "/tmp/navigan-bootstrap.json"]),
            mock.patch("urllib.request.urlopen", return_value=io.BytesIO(
                json.dumps(enrollment).encode())),
            mock.patch("subprocess.check_output", return_value="test-ecr-password\n") as ecr,
            mock.patch("subprocess.run") as run,
        ):
            exec(compile(installer, "<ssm bootstrap>", "exec"), {"__name__": "__main__"})

        ecr.assert_called_once()
        manifest = run.call_args_list[0].kwargs["input"]
        self.assertIn("name: navigan-source-" + "a" * 32 + "-image-pull", manifest)
        self.assertIn("imagePullSecrets:\n      - name: navigan-source-" + "a" * 32 + "-image-pull", manifest)
        self.assertIn("type: kubernetes.io/dockerconfigjson", manifest)
        self.assertIn(REPOSITORY + "@" + DIGEST, manifest)
        self.assertNotIn("test-ecr-password", manifest)
