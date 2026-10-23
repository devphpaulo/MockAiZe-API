from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from unittest.mock import patch
import unittest

from mockaize_api.cli import main
from mockaize_api.config import ConfigurationError
from mockaize_api.preflight import PreflightError


class CliTests(unittest.TestCase):
    def test_failed_validation_returns_nonzero_and_safe_json(self):
        for error in [ConfigurationError('config', 'JSON inválido.'),
                      PreflightError('port', 'Porta indisponível.')]:
            with self.subTest(error=error), patch('mockaize_api.cli.load_config', side_effect=error):
                output, errors = StringIO(), StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    status = main(['--config', 'missing.json', '--check'])
                self.assertEqual(status, 1)
                self.assertEqual(output.getvalue(), '')
                problem = json.loads(errors.getvalue())
                self.assertEqual(problem['code'], 'PREFLIGHT_FAILED')
                self.assertEqual(problem['field'], error.field)
                self.assertNotIn('missing.json', errors.getvalue())

    def test_success_is_reported_only_after_environment_check(self):
        with patch('mockaize_api.cli.load_config') as load, patch('mockaize_api.cli.check_environment') as check:
            output = StringIO()
            with redirect_stdout(output):
                status = main(['--config', 'config.json', '--check'])
            check.assert_called_once_with(load.return_value)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'preflight-passed')

    def test_start_without_check_does_not_claim_to_run_service(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
            main([])
        self.assertEqual(error.exception.code, 2)
