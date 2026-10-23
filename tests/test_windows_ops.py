from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mockaize_api.config import ApiConfig, save_config
from mockaize_api.windows_ops import (CONFIG_EXE, SERVICE_EXE, Installation, Installer,
                                     validate_origins, wait_health)


class FakeDriver:
    def __init__(self, status='stopped'):
        self.state = status
        self.events = []

    def status(self):
        self.events.append('query')
        return self.state

    def stop(self):
        self.events.append('stop')
        self.state = 'stopped'

    def start(self):
        self.events.append('start')
        self.state = 'running'

    def configure(self, installation, config):
        self.events.append(('configure', config.port))

    def remove_registration(self):
        self.events.append('remove')

    def remove_binaries(self, directory):
        self.events.append(('remove binaries', directory))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.payload = self.root / 'payload'
        self.payload.mkdir()
        for executable in (SERVICE_EXE, CONFIG_EXE):
            (self.payload / executable).write_text('new binary')
        self.target = self.root / 'installed'
        self.target.mkdir()
        (self.target / SERVICE_EXE).write_text('old binary')
        self.data = self.root / 'data'
        self.data.mkdir()
        self.config = ApiConfig(self.root / 'studio.db', self.data / 'input',
                                self.data / 'output', self.data / 'logs', 8123, '127.0.0.1', 'N')
        self.path = self.data / 'config.json'
        save_config(self.path, self.config)
        for name in ('credentials.json', 'state.sqlite3', 'important.xml'):
            (self.data / name).write_text('preserve ' + name)
        self.original = {path: path.read_bytes() for path in self.data.iterdir()}
        self.driver = FakeDriver()
        self.installer = Installer(Installation(self.target, self.path), self.driver)
        preflight = patch('mockaize_api.preflight.check_environment')
        preflight.start()
        self.addCleanup(preflight.stop)

    def assert_preserved(self):
        for path, content in self.original.items():
            self.assertEqual(path.read_bytes(), content)

    def test_running_or_pending_service_blocks_binary_swap(self):
        for state in ('running', 'pending'):
            with self.subTest(state=state):
                self.driver.state = state
                with self.assertRaisesRegex(RuntimeError, 'execução'):
                    self.installer.install(self.payload)
                self.assertEqual((self.target / SERVICE_EXE).read_text(), 'old binary')
                self.assert_preserved()

    def test_scm_is_queried_again_after_staging(self):
        with patch.object(self.driver, 'status', side_effect=['stopped', 'stopped', 'running']):
            with self.assertRaisesRegex(RuntimeError, 'execução'):
                self.installer.install(self.payload)
        self.assertEqual((self.target / SERVICE_EXE).read_text(), 'old binary')
        self.assertFalse(self.target.with_name('installed.staging').exists())

    def test_update_uses_saved_port_and_preserves_all_data(self):
        with patch('mockaize_api.windows_ops.wait_health') as health:
            self.assertIsNone(self.installer.install(self.payload))
        self.assertEqual(health.call_args.args[0].port, 8123)
        self.assertEqual((self.target / SERVICE_EXE).read_text(), 'new binary')
        self.assertFalse(self.target.with_name('installed.rollback').exists())
        self.assert_preserved()

    def test_health_failure_rolls_back_binaries_and_leaves_data(self):
        with patch('mockaize_api.windows_ops.wait_health', side_effect=RuntimeError('health failed')):
            with self.assertRaisesRegex(RuntimeError, 'health failed'):
                self.installer.install(self.payload)
        self.assertEqual((self.target / SERVICE_EXE).read_text(), 'old binary')
        self.assertEqual(self.driver.state, 'stopped')
        self.assert_preserved()

    def test_first_install_failure_removes_only_new_config_and_unshown_key(self):
        def create(config_path):
            (config_path.parent / 'credentials.json').write_text('hashed key')
            return 'one-time-key'
        key_creation = patch('mockaize_api.security.create_credentials', side_effect=create)
        key_creation.start()
        self.addCleanup(key_creation.stop)
        self.path.unlink()
        (self.data / 'credentials.json').unlink()
        with patch('mockaize_api.windows_ops.wait_health', side_effect=RuntimeError('unhealthy')):
            with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
                self.installer.install(self.payload, self.config)
        self.assertFalse(self.path.exists())
        self.assertFalse((self.data / 'credentials.json').exists())
        self.assertEqual((self.data / 'important.xml').read_text(), 'preserve important.xml')
        self.assertEqual((self.data / 'state.sqlite3').read_text(), 'preserve state.sqlite3')
        # Retry may now create a usable token and display it only on success.
        with patch('mockaize_api.windows_ops.wait_health'):
            token = self.installer.install(self.payload, self.config)
        self.assertIsInstance(token, str)
        self.assertTrue((self.data / 'credentials.json').exists())

    def test_first_install_failure_preserves_preexisting_key(self):
        self.path.unlink()
        credential = (self.data / 'credentials.json').read_bytes()
        with patch('mockaize_api.windows_ops.wait_health', side_effect=RuntimeError('unhealthy')):
            with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
                self.installer.install(self.payload, self.config)
        self.assertEqual((self.data / 'credentials.json').read_bytes(), credential)
        self.assertFalse(self.path.exists())

    def test_explicit_invalid_config_repair_preserves_original(self):
        self.path.write_bytes(b'invalid JSON')
        with patch('mockaize_api.windows_ops.wait_health'):
            self.installer.install(self.payload, self.config)
        self.assertEqual(self.path.with_name('config.invalid-backup.json').read_bytes(), b'invalid JSON')
        self.assertIn(b'8123', self.path.read_bytes())

    def test_incomplete_package_does_not_mutate_installation(self):
        (self.payload / CONFIG_EXE).unlink()
        with self.assertRaisesRegex(RuntimeError, 'incompleto'):
            self.installer.install(self.payload)
        self.assertEqual((self.target / SERVICE_EXE).read_text(), 'old binary')
        self.assert_preserved()

    def test_stale_backup_is_preserved(self):
        backup = self.target.with_name('installed.rollback')
        backup.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'recuperação'):
            self.installer.install(self.payload)
        self.assertTrue(backup.exists())

    def test_uninstall_preserves_all_data(self):
        self.installer.uninstall()
        self.assert_preserved()
        self.assertIn('remove', self.driver.events)

    def test_config_failure_restores_previous_configuration(self):
        replacement = ApiConfig(self.config.database_path, self.config.input_directory,
                                self.config.output_directory, self.config.logs_directory,
                                9999, '127.0.0.1', 'N')
        with patch('mockaize_api.windows_ops.wait_health', side_effect=RuntimeError('unhealthy')):
            with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
                self.installer.change_config(replacement, 'LocalSubnet')
        self.assert_preserved()
        self.assertEqual(self.driver.state, 'running')

    def test_failed_repair_removes_new_service_but_preserves_saved_config(self):
        self.driver.state = 'absent'
        with patch('mockaize_api.windows_ops.wait_health', side_effect=RuntimeError('unhealthy')):
            with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
                self.installer.install(self.payload)
        self.assertIn('remove', self.driver.events)
        self.assert_preserved()

    def test_failed_config_edit_restores_original_network_origins(self):
        original = Installation(self.target, self.path, '10.0.0.0/24')
        installer = Installer(original, self.driver)
        with patch.object(self.driver, 'configure') as configure:
            with patch('mockaize_api.windows_ops.wait_health', side_effect=RuntimeError('unhealthy')):
                with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
                    installer.change_config(self.config, '192.168.2.0/24')
        self.assertEqual(configure.call_args_list[0].args[0].origins, '192.168.2.0/24')
        self.assertEqual(configure.call_args_list[-1].args[0].origins, '10.0.0.0/24')

    def test_invalid_edit_restarts_previous_service(self):
        with patch('mockaize_api.preflight.check_environment', side_effect=RuntimeError('port occupied')):
            with self.assertRaisesRegex(RuntimeError, 'port occupied'):
                self.installer.change_config(self.config, 'LocalSubnet')
        self.assertEqual(self.driver.state, 'running')
        self.assert_preserved()

    def test_invalid_origins_edit_restarts_previous_service(self):
        with self.assertRaises(ValueError):
            self.installer.change_config(self.config, 'any')
        self.assertEqual(self.driver.state, 'running')
        self.assert_preserved()

    def test_allowed_origins_are_narrow_and_no_commands(self):
        self.assertEqual(validate_origins('LocalSubnet, 192.168.1.0/24'), 'LocalSubnet,192.168.1.0/24')
        for value in ('*', 'any', '0.0.0.0/0', '::/0', 'LocalSubnet,,', '10.0.0.1 & whoami'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_origins(value)

    def test_health_request_is_root_saved_port_and_ignores_proxy(self):
        with patch('mockaize_api.windows_ops.build_opener') as build:
            response = build.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"status":"ok"}'
            wait_health(self.config, timeout=0)
        self.assertEqual(build.return_value.open.call_args.args[0], 'http://127.0.0.1:8123/health')
