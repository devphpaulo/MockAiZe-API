import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mockaize_api.config import ApiConfig, ConfigurationError, load_config, save_config


class ConfigurationTests(unittest.TestCase):
    def test_cleanup_rejects_another_registered_windows_profile_for_service_account(self):
        profile = self.root / 'other-profile'
        values = dict(self.values, inputDirectory=str(profile), cleanup={'inputs': {'mode': 'age', 'days': 1}})
        with patch('mockaize_api.config._windows_profile_paths', return_value={profile}):
            with self.assertRaises(ConfigurationError):
                from mockaize_api.config import ApiConfig
                ApiConfig.from_mapping(values)

    def test_windows_profile_discovery_fails_closed_for_invalid_locations(self):
        from contextlib import nullcontext
        import os
        import sys
        from types import SimpleNamespace
        from mockaize_api.config import _windows_profile_paths
        for value in ('', 'relative-profile', str(self.root / '%MISSING_PROFILE_VARIABLE%')):
            registry = SimpleNamespace(HKEY_LOCAL_MACHINE=1,
                OpenKey=lambda *args: nullcontext(1), QueryInfoKey=lambda *args: (1, 0, 0),
                EnumKey=lambda *args: 'SID', QueryValueEx=lambda key, name: (
                    str(self.root / 'profiles') if name == 'ProfilesDirectory' else value, 1))
            with self.subTest(value=value), patch.dict(sys.modules, winreg=registry), \
                    patch('mockaize_api.config.os', SimpleNamespace(name='nt', path=os.path)):
                with self.assertRaises(ConfigurationError):
                    _windows_profile_paths()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.path = self.root / 'config.json'
        self.values = {
            'databasePath': str(self.root / 'source.sqlite3'),
            'inputDirectory': str(self.root / 'Entradas'),
            'outputDirectory': str(self.root / 'Saídas'),
            'logsDirectory': str(self.root / 'Logs'),
            'port': 6578, 'host': '127.0.0.1', 'firewallAccess': 'N',
        }

    def write(self, values=None):
        self.path.write_text(json.dumps(self.values if values is None else values), encoding='utf-8')

    def test_valid_configuration_preserves_absolute_unicode_paths(self):
        self.write()
        config = load_config(self.path)
        self.assertEqual(config.output_directory, self.root / 'Saídas')
        self.assertEqual(config.port, 6578)

    def test_network_configuration_requires_matching_host(self):
        self.values.update(host='0.0.0.0', firewallAccess='Y')
        self.write()
        self.assertEqual(load_config(self.path).host, '0.0.0.0')

    def test_invalid_fields_fail_without_echoing_values(self):
        cases = [('port', True), ('port', 1.5), ('port', '6578'), ('port', 0),
                 ('port', 65536), ('host', '0.0.0.0'), ('firewallAccess', 'Y'),
                 ('databasePath', 'relative.sqlite3'), ('inputDirectory', None),
                 ('apiKey', 'secret-do-not-echo'), ('logsDirectory', self.values['outputDirectory'])]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                values = dict(self.values, **{field: value})
                self.write(values)
                with self.assertRaises(ConfigurationError) as error:
                    load_config(self.path)
                self.assertNotIn('secret-do-not-echo', str(error.exception))
                self.assertNotIn(str(self.root), str(error.exception))

    def test_missing_fields_and_non_object_json_are_rejected(self):
        for values in [{}, [], None, {'port': 6578}]:
            with self.subTest(values=values):
                self.write(values) if values is not None else self.path.write_text('null')
                with self.assertRaises(ConfigurationError):
                    load_config(self.path)

    def test_duplicate_keys_invalid_encoding_and_large_json_are_rejected(self):
        for content in [b'{"port": 1, "port": 2}', b'\xff', b'{' , b' ' * 65537]:
            with self.subTest(content=content[:30]):
                self.path.write_bytes(content)
                with self.assertRaises(ConfigurationError):
                    load_config(self.path)

    def test_missing_file_is_not_created(self):
        with self.assertRaises(ConfigurationError):
            load_config(self.path)
        self.assertFalse(self.path.exists())

    def test_atomic_save_round_trips_and_cleans_temporary_file(self):
        self.write()
        config = load_config(self.path)
        save_config(self.path, config)
        self.assertEqual(load_config(self.path), config)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_failed_replace_preserves_existing_configuration(self):
        self.write()
        original = self.path.read_bytes()
        config = load_config(self.path)
        with patch('mockaize_api.config.os.replace', side_effect=PermissionError):
            with self.assertRaises(ConfigurationError):
                save_config(self.path, config)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_expanded_configuration_round_trips_without_losing_options(self):
        self.values.update(
            presetsDirectory=str(self.root / 'Regras áé'),
            authentication={'required': False},
            limits={'inputXml': {'mode': 'custom', 'bytes': 3000000},
                    'records': {'mode': 'disabled'}},
            cleanup={'inputs': {'mode': 'age', 'days': 7},
                     'outputs': {'mode': 'disabled'}, 'logs': {'mode': 'age', 'days': 45}})
        self.write()
        config = load_config(self.path)
        self.assertEqual(config.presets_directory, self.root / 'Regras áé')
        self.assertFalse(config.authentication.required)
        save_config(self.path, config)
        self.assertEqual(load_config(self.path), config)
        self.assertEqual(config.to_mapping(), self.values)

    def test_legacy_defaults_and_constructor_are_compatible(self):
        config = ApiConfig.from_mapping(self.values)
        self.assertEqual(config.presets_directory, self.root / 'Presets')
        self.assertTrue(config.authentication.required)
        direct = ApiConfig(config.database_path, config.input_directory, config.output_directory,
                           config.logs_directory, config.port, config.host, config.firewall_access)
        self.assertEqual(direct, config)

    def test_optional_fields_reject_unknown_keys_types_and_invalid_modes(self):
        invalid = [
            {'authentication': {'required': 1}}, {'authentication': {'users': []}},
            {'authentication': None}, {'presetsDirectory': 'relative'},
            {'limits': {'outputXml': {'mode': 'disabled'}}},
            {'limits': {'inputXml': {'mode': 'custom', 'bytes': True}}},
            {'limits': {'inputXml': {'mode': 'custom', 'bytes': 0}}},
            {'limits': {'records': {'mode': 'custom', 'count': -1}}},
            {'limits': {'records': {'mode': 'custom'}}},
            {'limits': {'records': {'mode': 'unknown'}}},
            {'limits': {'records': {'mode': 'disabled', 'count': 1000}}},
            {'cleanup': {'inputs': {'mode': 'age', 'days': 0}}},
            {'cleanup': {'logs': {'mode': 'age', 'days': True}}},
            {'cleanup': {'outputs': {'mode': 'daily', 'days': 1}}},
            {'cleanup': {'unknown': {'mode': 'disabled'}}},
        ]
        for additions in invalid:
            with self.subTest(additions=additions), self.assertRaises(ConfigurationError):
                ApiConfig.from_mapping({**self.values, **additions})

    def test_cleanup_rejects_overlapping_roots_and_protected_presets_or_database(self):
        invalid = [
            {'outputDirectory': str(self.root)},
            {'presetsDirectory': str(self.root / 'Logs' / 'Presets')},
            {'logsDirectory': str(self.root / 'Presets' / 'nested')},
            {'databasePath': str(self.root / 'Logs' / 'studio.db')},
            {'logsDirectory': str(Path(self.root.anchor))},
            {'logsDirectory': str(Path.home())},
        ]
        for additions in invalid:
            with self.subTest(additions=additions), self.assertRaises(ConfigurationError):
                ApiConfig.from_mapping({**self.values, **additions,
                                        'cleanup': {'outputs': {'mode': 'age', 'days': 2},
                                                    'logs': {'mode': 'age', 'days': 3}}})

    def test_disabled_cleanup_does_not_reject_legacy_overlapping_paths(self):
        config = ApiConfig.from_mapping({**self.values,
                                         'inputDirectory': str(self.root / 'shared'),
                                         'outputDirectory': str(self.root / 'shared' / 'outputs'),
                                         'cleanup': {'logs': {'mode': 'disabled'}}})
        self.assertEqual(config.input_directory, self.root / 'shared')
