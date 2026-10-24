import configparser
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import types
from unittest.mock import Mock, patch

from fixtures.catalog_factory import create_catalog
from mockaize_api import maintenance
from mockaize_api.config import ApiConfig, save_config
from mockaize_api.windows_ops import Installation
from mockaize_api.windows_ops import WindowsDriver


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.data = self.root / 'Dados'
        self.data.mkdir()
        self.source = self.root / 'source.sqlite3'
        create_catalog(self.source)
        self.config = ApiConfig(self.source, self.data / 'Entradas', self.data / 'Saídas',
                                self.data / 'Logs', 6578, '127.0.0.1', 'N')
        self.installation = Installation(self.root / 'bin', self.data / 'config.json')
        self.installation.directory.mkdir()
        save_config(self.installation.config_path, self.config)
        self.driver = Mock()
        self.driver.status.return_value = 'stopped'
        self.driver.remove_binaries.return_value = True
        target = patch.object(maintenance, '_discover', return_value=(self.installation, True))
        target.start()
        self.addCleanup(target.stop)

    def request(self):
        return {**self.config.to_mapping(), 'installDir': str(self.installation.directory),
                'configPath': str(self.installation.config_path), 'origins': 'LocalSubnet'}

    def test_unicode_ini_and_percent_characters_round_trip_without_interpolation(self):
        path = self.root / 'pedido.ini'
        path.write_text('[setup]\noutputDirectory=C:\\Saídas\\100%\n', encoding='utf-16')
        self.assertEqual(maintenance.read_request(path)['outputDirectory'], 'C:\\Saídas\\100%')
        reply = self.root / 'result.ini'
        maintenance.write_result(reply, {'ok': '1', 'message': 'Saídas 100%', 'apiKey': 'secret'})
        parsed = configparser.ConfigParser(interpolation=None)
        parsed.read(reply, encoding='utf-16')
        self.assertEqual(parsed['result']['message'], 'Saídas 100%')
        self.assertEqual(parsed['result']['apiKey'], 'secret')

    def test_inspection_preserves_saved_config_and_reports_real_service_state(self):
        result = maintenance.execute('inspect', {}, self.driver)
        self.assertEqual(result['state'], 'stopped')
        self.assertEqual(result['outputDirectory'], str(self.config.output_directory))
        self.assertNotIn('apiKey', result)
        self.driver.stop.assert_not_called()

    def test_inspection_without_installation_is_read_only(self):
        with patch.object(maintenance, '_discover', return_value=(None, False)):
            result = maintenance.execute('inspect', {}, self.driver)
        self.assertEqual(result['state'], 'absent')
        self.assertNotIn('installDir', result)

    def test_target_mismatch_is_rejected_before_any_mutation(self):
        request = self.request()
        request['installDir'] = str(self.root / 'other')
        with self.assertRaises(maintenance.MaintenanceError):
            maintenance.execute('stop', request, self.driver)
        self.driver.stop.assert_not_called()

    def test_stop_requires_observed_stopped_status(self):
        self.driver.status.return_value = 'running'
        with self.assertRaisesRegex(RuntimeError, 'execução'):
            maintenance.execute('stop', self.request(), self.driver)

    def test_validation_does_not_implicitly_stop_running_service(self):
        self.driver.status.return_value = 'running'
        with self.assertRaises(maintenance.MaintenanceError):
            maintenance.execute('validate', self.request(), self.driver)
        self.driver.stop.assert_not_called()

    def test_cleanup_is_blocked_until_service_is_absent(self):
        with self.assertRaises(maintenance.MaintenanceError):
            maintenance.execute('cleanup', self.request(), self.driver)
        self.driver.remove_binaries.assert_not_called()

    def test_cleanup_rejects_a_folder_not_in_the_saved_configuration(self):
        self.driver.status.return_value = 'absent'
        request = self.request()
        request.update(folderCount='1', folder0=str(self.root / 'unrelated'))
        with self.assertRaises(ValueError):
            maintenance.execute('cleanup', request, self.driver)
        self.driver.remove_binaries.assert_not_called()
        self.assertTrue(self.source.exists())

    def test_cleanup_preserves_data_by_default(self):
        self.driver.status.return_value = 'absent'
        result = maintenance.execute('cleanup', self.request(), self.driver)
        self.assertEqual(result['restartRequired'], '0')
        self.driver.remove_binaries.assert_not_called()
        self.assertTrue(self.installation.config_path.exists())

    def test_cleanup_reports_locked_binaries_for_reboot(self):
        self.driver.status.return_value = 'absent'
        request = self.request()
        request['cleanBinaries'] = '1'
        result = maintenance.execute('cleanup', request, self.driver)
        self.assertEqual(result['restartRequired'], '1')
        self.driver.remove_binaries.assert_called_once_with(self.installation.directory)

    def test_detach_reports_folders_only_after_confirmed_removal(self):
        with patch.object(maintenance, 'UninstallSession') as session:
            session.return_value.folders = [self.data]
            result = maintenance.execute('detach', self.request(), self.driver)
            session.return_value.detach.assert_called_once()
        self.assertEqual(result['folder0'], str(self.data))

    def test_secret_is_returned_in_private_ini_and_not_stdout(self):
        request, result = self.root / 'request.ini', self.root / 'result.ini'
        request.write_text('[setup]\n', encoding='utf-16')
        output = io.StringIO()
        with patch.object(maintenance, 'execute', return_value={'ok': '1', 'apiKey': 'secret'}), \
                contextlib.redirect_stdout(output):
            code = maintenance.main(['--maintenance', 'install', '--request', str(request), '--result', str(result)])
        self.assertEqual(code, 0)
        self.assertNotIn('secret', output.getvalue())
        self.assertIn('secret', result.read_text(encoding='utf-16'))

    def test_errors_do_not_leak_arbitrary_exception_contents(self):
        self.assertNotIn('private-token', maintenance._safe_message(RuntimeError('private-token')))

    def test_parent_of_locked_runtime_is_also_scheduled_for_reboot(self):
        runtime = self.installation.directory / '_internal'
        runtime.mkdir()
        locked = runtime / 'python.dll'
        locked.write_bytes(b'fixture')
        real_unlink = Path.unlink
        scheduled = Mock()
        def unlink(path, *args, **kwargs):
            if path == locked:
                raise PermissionError('simulated loaded DLL')
            return real_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', unlink), patch.dict('sys.modules', {
                'win32api': types.SimpleNamespace(MoveFileEx=scheduled),
                'win32con': types.SimpleNamespace(MOVEFILE_DELAY_UNTIL_REBOOT=4)}):
            self.assertTrue(WindowsDriver().remove_binaries(self.installation.directory))
        self.assertEqual([call.args[0] for call in scheduled.call_args_list],
                         [str(locked), str(runtime), str(self.installation.directory)])
