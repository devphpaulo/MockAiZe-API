import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mockaize_api.config import ConfigurationError, load_config, save_config


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
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
