import json
import os
import unittest
from unittest.mock import MagicMock, patch

from navigan.shared import database, diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_failure_does_not_expose_exception_contents(self):
        with self.assertLogs(diagnostics.logger, level='INFO') as logs:
            with self.assertRaises(ValueError):
                with diagnostics.phase('secret_decode'):
                    raise ValueError('private-password')
        self.assertNotIn('private-password', ''.join(logs.output))
        self.assertIn('"status": "failed"', logs.output[-1])

    def test_invocation_context_is_cleared(self):
        @diagnostics.invocation
        def handler(event, context):
            raise RuntimeError('private-token')
        with self.assertLogs(diagnostics.logger, level='INFO') as logs:
            with self.assertRaises(RuntimeError):
                handler({}, type('Context', (), {'aws_request_id': 'request-123'})())
        self.assertIn('request-123', logs.output[-1])
        self.assertEqual(diagnostics._context.get(), {})

    def test_secret_timeout_precedes_database_connection(self):
        database._cache.clear()
        client = MagicMock()
        client.get_secret_value.side_effect = TimeoutError('private-secret')
        with patch.dict(os.environ, {'AWS_LAMBDA_FUNCTION_NAME': 'test', 'DB_SECRET_ARN': 'test-arn'}):
            with patch('boto3.client', return_value=client) as factory, patch('psycopg.connect') as connect:
                with self.assertLogs(diagnostics.logger, level='INFO') as logs:
                    with self.assertRaises(TimeoutError):
                        database.connect()
                config = factory.call_args.kwargs['config']
                self.assertEqual(config.connect_timeout, 3)
                self.assertEqual(config.read_timeout, 3)
                self.assertEqual(config.retries['total_max_attempts'], 1)
                connect.assert_not_called()
        self.assertIn('"stage": "secret_fetch"', logs.output[-1])
        self.assertNotIn('private-secret', ''.join(logs.output))
