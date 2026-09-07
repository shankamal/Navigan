"""Exercise release scripts with fake AWS/Docker executables; never contact AWS."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = '123456789012.dkr.ecr.ap-south-1.amazonaws.com/navigan/frontend'
DIGEST = 'sha256:' + 'a' * 64
STUB = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps([name, args]) + '\\n')
if name == 'docker':
    if args[:1] == ['login']: sys.stdin.read()
    if args[:2] == ['buildx', 'build'] and os.environ.get('FAIL_BUILD'): sys.exit(7)
    sys.exit(0)
query = args[args.index('--query')+1] if '--query' in args else ''
if 'describe-stacks' in args:
    if 'RepositoryUri' in query: print(os.environ['REPO'])
    elif 'RepositoryArn' in query: print('arn:aws:ecr:ap-south-1:123456789012:repository/navigan/frontend')
    elif 'ClusterName' in query: print('cluster')
    elif 'ServiceName' in query: print('service')
    else: print('[]')
elif 'get-login-password' in args: print('test-only-password')
elif 'describe-images' in args: print(os.environ['DIGEST'])
elif 'describe-services' in args: print('task-definition')
elif 'describe-task-definition' in args: print(os.environ.get('ACTIVE_IMAGE', os.environ['IMAGE_URI']))
elif 'get-caller-identity' in args: print('123456789012')
'''


class ReleaseScripts(unittest.TestCase):
    def run_script(self, script, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for command in ('aws', 'docker'):
                path = folder / command
                path.write_text(STUB)
                path.chmod(0o755)
            log = folder / 'calls.jsonl'
            env = {**os.environ, 'PATH': f'{folder}:{os.environ["PATH"]}',
                   'AWS_REGION': 'ap-south-1', 'AWS_PROFILE': 'test-profile',
                   'NEXT_PUBLIC_OIDC_AUTHORITY': 'https://issuer.test',
                   'NEXT_PUBLIC_OIDC_CLIENT_ID': 'public-client',
                   'NEXT_PUBLIC_APP_URL': 'https://navigan.test',
                   'NEXT_PUBLIC_COGNITO_DOMAIN': '', 'IMAGE_TAG': 'test-tag',
                   'VPC_ID': 'vpc-123', 'PUBLIC_SUBNET_IDS': 'subnet-1,subnet-2',
                   'PRIVATE_SUBNET_IDS': 'subnet-3,subnet-4',
                   'CERTIFICATE_ARN': 'arn:aws:acm:ap-south-1:123456789012:certificate/test',
                   'CALL_LOG': str(log), 'REPO': REPO, 'DIGEST': DIGEST,
                   'IMAGE_URI': f'{REPO}@{DIGEST}', **overrides}
            result = subprocess.run(['bash', str(ROOT / 'scripts/frontend' / script)],
                                    env=env, capture_output=True, text=True, check=False)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_build_returns_only_digest_and_uses_profile_and_amd64(self):
        result, calls = self.run_script('build-and-push.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f'{REPO}@{DIGEST}')
        aws_calls = [args for name, args in calls if name == 'aws']
        self.assertTrue(all('--profile' in args and 'test-profile' in args for args in aws_calls))
        build = next(args for name, args in calls if name == 'docker' and args[:2] == ['buildx', 'build'])
        self.assertIn('linux/amd64', build)

    def test_failed_build_never_pushes(self):
        result, calls = self.run_script('build-and-push.sh', FAIL_BUILD='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(name == 'docker' and args[:1] == ['push'] for name, args in calls))
        self.assertEqual(result.stdout, '')

    def test_deploy_detects_rollback_to_another_image(self):
        result, _ = self.run_script('deploy.sh', ACTIVE_IMAGE=REPO + '@sha256:' + 'b' * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not running the requested image', result.stderr)

    def test_invalid_scaling_and_mutable_tag_rejected_before_deploy(self):
        for overrides in ({'MIN_TASKS': '5', 'MAX_TASKS': '2'}, {'IMAGE_URI': REPO + ':latest'}):
            result, calls = self.run_script('deploy.sh', **overrides)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any('deploy' in args for _, args in calls))

    def test_deploy_success_waits_for_service(self):
        result, calls = self.run_script('deploy.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any('services-stable' in args for _, args in calls))


if __name__ == '__main__':
    unittest.main()
