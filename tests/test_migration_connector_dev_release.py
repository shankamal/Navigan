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

REPOSITORY = (
    "905418045935.dkr.ecr.ap-south-1.amazonaws.com/"
    "navigan/migration-source-connector"
)
DIGEST = "sha256:" + "a" * 64


def parse_parameters(config, environment):
    tokens = shlex.split(config[environment]["deploy"]["parameters"]["parameter_overrides"])
    return dict(token.split("=", 1) for token in tokens)


class DevConnectorReleaseTests(unittest.TestCase):
    def test_pinning_preserves_production_and_other_dev_parameters(self):
        before = (ROOT / "samconfig.toml").read_text(encoding="utf-8")
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
                    if name != "SourceConnectorDeliveryRoleArn":
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
        self.assertIn("name: navigan-migration-image-pull", manifest)
        self.assertIn("imagePullSecrets:\n      - name: navigan-migration-image-pull", manifest)
        self.assertIn("type: kubernetes.io/dockerconfigjson", manifest)
        self.assertIn(REPOSITORY + "@" + DIGEST, manifest)
        self.assertNotIn("test-ecr-password", manifest)
