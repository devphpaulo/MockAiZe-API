from dataclasses import asdict
import json
from pathlib import Path
import pickle
import tempfile
import unittest

from mockaize_api.config import ApiConfig, ConfigurationError
from mockaize_api.errors import ApiError
from mockaize_api.policy import Policy


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'config.json'
        self.values = {'databasePath': str(self.root / 'studio.db'),
                       'inputDirectory': str(self.root / 'inputs'),
                       'outputDirectory': str(self.root / 'outputs'),
                       'logsDirectory': str(self.root / 'logs'),
                       'port': 6578, 'host': '127.0.0.1', 'firewallAccess': 'N'}

    def resolve(self, **additions):
        return Policy.load(self.path).resolve(ApiConfig.from_mapping({**self.values, **additions}),
                                              config_path=self.path)

    def test_defaults_resolve_to_one_serializable_policy(self):
        policy = self.resolve()
        self.assertEqual(policy.input_xml_bytes, 2000000)
        self.assertEqual(policy.record_count, 500)
        self.assertIsNone(policy.cleanup_inputs_days)
        self.assertIsNone(policy.cleanup_outputs_days)
        self.assertEqual(policy.cleanup_logs_days, 30)
        self.assertEqual(pickle.loads(pickle.dumps(policy)), policy)
        self.assertEqual(json.loads(json.dumps(policy.to_mapping())), asdict(policy))
        self.assertFalse(any('output' in key and 'bytes' in key for key in policy.to_mapping()))

    def test_custom_and_disabled_limits_remain_distinct_from_defaults(self):
        policy = self.resolve(limits={'inputXml': {'mode': 'custom', 'bytes': 3000000},
                                      'records': {'mode': 'custom', 'count': 1000}})
        self.assertEqual((policy.input_xml_bytes, policy.record_count), (3000000, 1000))
        policy = self.resolve(limits={'inputXml': {'mode': 'disabled'},
                                      'records': {'mode': 'disabled'}})
        self.assertEqual((policy.input_xml_bytes, policy.record_count), (None, None))

    def test_explicit_log_cleanup_wins_over_legacy_retention_even_when_disabled(self):
        (self.root / 'policy.json').write_text(json.dumps({'logs_retention_days': 17,
                                                        'requests_per_second': 9}))
        self.assertEqual(self.resolve().cleanup_logs_days, 17)
        self.assertEqual(self.resolve(cleanup={'logs': {'mode': 'age', 'days': 8}}).cleanup_logs_days, 8)
        policy = self.resolve(cleanup={'logs': {'mode': 'disabled'}})
        self.assertIsNone(policy.cleanup_logs_days)
        self.assertEqual(policy.requests_per_second, 9)

    def test_omitted_log_cleanup_survives_config_round_trip_for_legacy_precedence(self):
        config = ApiConfig.from_mapping(self.values)
        config = ApiConfig.from_mapping(config.to_mapping())
        self.assertEqual(Policy(logs_retention_days=13).resolve(config).cleanup_logs_days, 13)

    def test_policy_file_rejects_duplicate_unknown_and_invalid_fields(self):
        for content in ['{"requests_per_second":1,"requests_per_second":2}',
                        '{"output_bytes":100}', '{"requests_per_second":true}',
                        '{"maximum_connections":0}', 'null']:
            with self.subTest(content=content):
                (self.root / 'policy.json').write_text(content)
                with self.assertRaises(ApiError):
                    Policy.load(self.path)

    def test_cleanup_cannot_enclose_config_state_or_installed_binaries(self):
        config = ApiConfig.from_mapping({**self.values, 'logsDirectory': str(self.root / 'private')})
        with self.assertRaises(ConfigurationError):
            Policy().resolve(config, config_path=self.root / 'private' / 'config.json')
        with self.assertRaises(ConfigurationError):
            Policy().resolve(config, protected_paths=(self.root / 'private' / 'bin',))
        with self.assertRaises(ConfigurationError):
            Policy().resolve(config, protected_paths=(self.root,))
