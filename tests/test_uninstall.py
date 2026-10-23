from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mockaize_api.config import ApiConfig, save_config
from mockaize_api.uninstall import UninstallSession, finish_uninstall, discover_uninstall_target
from mockaize_api.windows_ops import Installation


class Driver:
    def __init__(self, fail=False):
        self.state = 'running'
        self.events = []
        self.fail = fail

    def status(self):
        return self.state

    def stop(self):
        self.events.append('stop')
        self.state = 'stopped'

    def remove_registration(self):
        self.events.append('remove-service')
        if not self.fail:
            self.state = 'absent'

    def wait_removed(self):
        self.events.append('verify-absent')
        if self.state != 'absent':
            raise RuntimeError('Serviço ainda listado.')

    def remove_binaries(self, directory):
        self.events.append(('remove-binaries', directory))
        return True


class UninstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.program = self.root / 'installed'
        self.program.mkdir()
        self.data = self.root / 'api-data'
        self.data.mkdir()
        self.database = self.root / 'studio.sqlite3'
        self.database.write_bytes(b'original studio database')
        self.config = ApiConfig(self.database, self.data / 'input', self.data / 'output',
                                self.data / 'logs', 6578, '127.0.0.1', 'N')
        for path in [self.config.input_directory, self.config.output_directory, self.config.logs_directory]:
            path.mkdir()
            (path / 'example.xml').write_text('<a/>')
        self.path = self.data / 'config.json'
        save_config(self.path, self.config)
        self.driver = Driver()
        self.session = UninstallSession(Installation(self.program, self.path), self.driver)

    def test_service_removal_is_confirmed_before_questions(self):
        self.session.detach()
        questions = []
        def ask(kind, path):
            self.assertEqual(self.driver.events, ['stop', 'remove-service', 'verify-absent'])
            questions.append((kind, path))
            return False
        result = finish_uninstall(self.session, ask)
        self.assertEqual(questions[0], ('binaries', self.program))
        self.assertTrue(any(kind == 'folder' for kind, _ in questions))
        self.assertEqual(sum(kind == 'folder' for kind, _ in questions), 1)
        self.assertFalse(result['restartRequired'])
        self.assertTrue(self.path.is_file())
        self.assertTrue(self.config.output_directory.is_dir())

    def test_failed_service_removal_never_prompts_or_cleans(self):
        self.driver.fail = True
        with self.assertRaises(RuntimeError):
            self.session.detach()
        with self.assertRaises(RuntimeError):
            self.session.cleanup(True, [self.data])
        self.assertTrue(self.path.is_file())
        self.assertFalse(any(isinstance(item, tuple) for item in self.driver.events))

    def test_user_can_remove_only_binaries_and_preserve_folders(self):
        self.session.detach()
        result = finish_uninstall(self.session, lambda kind, path: kind == 'binaries')
        self.assertTrue(result['restartRequired'])
        self.assertIn(('remove-binaries', self.program), self.driver.events)
        self.assertTrue(self.path.is_file())

    def test_user_can_remove_folders_preserving_bins_and_source_database(self):
        self.session.detach()
        finish_uninstall(self.session, lambda kind, path: kind == 'folder')
        self.assertFalse(self.data.exists())
        self.assertTrue(self.program.is_dir())
        self.assertEqual(self.database.read_bytes(), b'original studio database')

    def test_cleanup_rejects_arbitrary_directory(self):
        self.session.detach()
        with self.assertRaises(ValueError):
            self.session.cleanup(False, [self.root])
        self.assertTrue(self.database.exists())
        self.assertTrue(self.path.exists())

    def test_directory_containing_studio_database_is_not_offered(self):
        config = replace(self.config, database_path=self.data / 'studio.sqlite3')
        config.database_path.write_bytes(b'preserve')
        save_config(self.path, config)
        session = UninstallSession(self.session.installation, self.driver)
        self.assertNotIn(self.data, session.folders)
        session.detach()
        with self.assertRaises(ValueError):
            session.cleanup(False, [self.data])
        self.assertTrue(config.database_path.exists())

    def test_invalid_configuration_preserves_unknown_folders(self):
        self.path.write_text('invalid')
        session = UninstallSession(self.session.installation, self.driver)
        self.assertEqual(session.folders, [])
        session.detach()
        session.cleanup(False, [])
        self.assertTrue(self.path.exists())

    def test_directory_link_is_rejected_before_deleting_any_data(self):
        external = self.root / 'external'
        external.mkdir()
        try:
            (self.data / 'link').symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest('Criação de symlink não permitida nesta conta Windows.')
        self.session.detach()
        with self.assertRaises(ValueError):
            self.session.cleanup(False, [self.data])
        self.assertTrue(self.path.exists())
        self.assertTrue(external.exists())

    def test_reparse_point_is_refused_without_requiring_symlink_privilege(self):
        self.session.detach()
        with patch('mockaize_api.uninstall._reparse', side_effect=lambda path: path == self.data):
            with self.assertRaises(ValueError):
                self.session.cleanup(False, [self.data])
        self.assertTrue(self.path.exists())

    def test_retained_receipt_allows_later_cleanup_without_service_registry(self):
        import json
        (self.program / 'installation.json').write_text(json.dumps({
            'product': 'MockAiZe API', 'version': 1, 'directory': str(self.program),
            'configPath': str(self.path), 'origins': 'LocalSubnet'}))
        with patch('mockaize_api.uninstall.discover_installation', return_value=None):
            installation = discover_uninstall_target(self.program / 'MockAiZeApiUninstall.exe')
        self.assertEqual(installation, self.session.installation)

    def test_receipt_cannot_redirect_deletion_to_another_directory(self):
        import json
        (self.program / 'installation.json').write_text(json.dumps({
            'product': 'MockAiZe API', 'version': 1, 'directory': str(self.root),
            'configPath': str(self.path)}))
        with patch('mockaize_api.uninstall.discover_installation', return_value=None):
            with self.assertRaises(RuntimeError):
                discover_uninstall_target(self.program / 'MockAiZeApiUninstall.exe')
