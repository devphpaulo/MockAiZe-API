from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from mockaize_api.config import ApiConfig, ConfigurationError, load_config, save_config
from mockaize_api.windows_ops import (CONFIG_EXE, SERVICE_EXE, UNINSTALL_EXE, Installation, Installer,
                                     SERVICE_SID, WindowsDriver, validate_origins, wait_health)


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

    def revoke_input_delete(self, config, root):
        self.events.append(('revoke input delete', config.input_directory))

    def remove_registration(self):
        self.events.append('remove')
        self.state = 'absent'

    def wait_removed(self):
        self.events.append('verify-absent')

    def remove_binaries(self, directory):
        self.events.append(('remove binaries', directory))


class InstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.payload = self.root / 'payload'
        self.payload.mkdir()
        for executable in (SERVICE_EXE, CONFIG_EXE, UNINSTALL_EXE):
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

    def test_installer_rejects_cleanup_over_binary_tree_before_mutation(self):
        from dataclasses import replace
        unsafe = replace(self.config, logs_directory=self.target)
        save_config(self.path, unsafe)
        with self.assertRaises(ConfigurationError):
            self.installer.install(self.payload)
        self.assertEqual((self.target / SERVICE_EXE).read_text(), 'old binary')
        self.assertFalse(self.target.with_name('installed.staging').exists())
        self.assertFalse(self.config.input_directory.exists())

    def test_configure_rejects_unsafe_cleanup_before_stopping_the_service(self):
        from dataclasses import replace
        unsafe = replace(self.config, logs_directory=self.target)
        with self.assertRaises(ConfigurationError):
            self.installer.change_config(unsafe, 'LocalSubnet')
        self.assertNotIn('stop', self.driver.events)
        self.assert_preserved()

    def test_configure_protects_the_executing_helper_before_stopping_service(self):
        from dataclasses import replace
        helper = self.root / 'python-host'
        unsafe = replace(self.config, logs_directory=helper)
        with patch('mockaize_api.windows_ops.sys.executable', str(helper / 'python.exe')):
            with self.assertRaises(ConfigurationError):
                self.installer.change_config(unsafe, 'LocalSubnet')
        self.assertNotIn('stop', self.driver.events)

    def test_input_cleanup_delete_grant_is_opt_in_and_does_not_replace_user_rights(self):
        from dataclasses import replace
        from mockaize_api.config import Cleanup, CleanupRule
        driver = WindowsDriver()
        with patch.object(driver, 'run') as run, \
                patch('mockaize_api.windows_ops._current_user_sid', return_value='S-1-5-21-123'):
            driver.configure_inputs(self.config, self.data)
            readonly = run.call_args_list
            run.reset_mock()
            enabled = replace(self.config, cleanup=Cleanup(inputs=CleanupRule('age', 7)))
            driver.configure_inputs(enabled, self.data)
            deletion = run.call_args_list
            run.reset_mock()
            driver.configure_inputs(self.config, self.data)
            disabled = run.call_args_list
        self.assertTrue(any('/grant:r' in call.args and f'{SERVICE_SID}:(OI)(CI)RX' in call.args
                            for call in readonly))
        self.assertTrue(any(f'{SERVICE_SID}:(OI)(IO)(DE)' in call.args for call in deletion))
        self.assertFalse(any(f'{SERVICE_SID}:(OI)(IO)(DE)' in call.args for call in disabled))
        self.assertTrue(any('*S-1-5-21-123:(OI)(CI)M' in call.args for call in disabled))
        self.assertFalse(any(f'{SERVICE_SID}:(OI)(CI)M' in call.args for call in deletion))

    def test_custom_local_preset_directory_gets_read_only_service_access(self):
        from dataclasses import replace
        from unittest.mock import MagicMock
        presets = self.root / 'custom-presets'
        config = replace(self.config, presets_directory=presets)
        driver = WindowsDriver()
        key = MagicMock()
        key.__enter__.return_value = key
        with patch('winreg.CreateKey', return_value=key), patch('winreg.SetValueEx'), \
                patch.object(driver, 'run') as run, patch.object(driver, 'firewall'), \
                patch.object(driver, 'register_shell'), patch.object(driver, 'configure_inputs'), \
                patch('mockaize_api.windows_ops._is_network_path', return_value=False):
            driver.configure(Installation(self.target, self.path), config)
        self.assertTrue(any('icacls.exe' in call.args and str(presets) in call.args and
                            f'{SERVICE_SID}:(OI)(CI)RX' in call.args for call in run.call_args_list))
        self.assertFalse(any('icacls.exe' in call.args and str(presets) in call.args and
                             f'{SERVICE_SID}:(OI)(CI)M' in call.args for call in run.call_args_list))

    def test_remote_input_permissions_are_not_changed_locally(self):
        driver = WindowsDriver()
        with patch('mockaize_api.windows_ops._is_network_path', return_value=True), \
                patch.object(driver, 'run') as run:
            driver.configure_inputs(self.config, self.data)
        run.assert_not_called()

    def test_moving_inputs_releases_old_delete_grant_and_rollback_releases_new_one(self):
        from dataclasses import replace
        from mockaize_api.config import Cleanup, CleanupRule
        old = replace(self.config, cleanup=Cleanup(inputs=CleanupRule('age', 7)))
        save_config(self.path, old)
        new = replace(old, input_directory=self.data / 'other-input')
        with patch('mockaize_api.windows_ops.wait_health', side_effect=RuntimeError('unhealthy')):
            with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
                self.installer.change_config(new, 'LocalSubnet')
        self.assertIn(('revoke input delete', old.input_directory), self.driver.events)
        self.assertIn(('revoke input delete', new.input_directory), self.driver.events)
        self.assertEqual(load_config(self.path).cleanup, old.cleanup)

    def test_failed_delete_revocation_does_not_prevent_configuration_and_service_rollback(self):
        from dataclasses import replace
        from mockaize_api.config import Cleanup, CleanupRule
        from mockaize_api import maintenance
        old = replace(self.config, cleanup=Cleanup(inputs=CleanupRule('age', 7)))
        save_config(self.path, old)
        new = replace(old, input_directory=self.data / 'other-input', port=9999)
        health_error = RuntimeError('PRIVATE-HEALTH')
        permission_error = PermissionError('PRIVATE-PERMISSION')
        def revoke(config, root):
            if config.input_directory == new.input_directory:
                raise permission_error
        with patch('mockaize_api.windows_ops.wait_health', side_effect=health_error), \
                patch.object(self.driver, 'revoke_input_delete', side_effect=revoke):
            with self.assertRaises(RuntimeError) as caught:
                self.installer.change_config(new, 'LocalSubnet')
        self.assertEqual(load_config(self.path), old)
        self.assertEqual(self.driver.state, 'running')
        self.assertEqual(self.driver.events[-2:], [('configure', old.port), 'start'])
        self.assertIs(caught.exception.original_error, health_error)
        self.assertIs(caught.exception.__cause__, permission_error)
        diagnostic = maintenance._safe_message(caught.exception)
        self.assertIn('exclusão', diagnostic)
        self.assertNotIn('PRIVATE', diagnostic)
        self.assertNotIn(str(self.root), diagnostic)

    def test_failed_config_restore_keeps_service_stopped_and_preserves_new_failure(self):
        from dataclasses import replace
        import mockaize_api.windows_ops as operations
        new = replace(self.config, port=9999)
        original_save = operations.save_config
        restore_error = PermissionError('PRIVATE-RESTORE')
        def save(path, config):
            if config.port == self.config.port:
                raise restore_error
            return original_save(path, config)
        with patch('mockaize_api.windows_ops.wait_health', side_effect=RuntimeError('PRIVATE-HEALTH')), \
                patch('mockaize_api.windows_ops.save_config', side_effect=save):
            with self.assertRaises(RuntimeError) as caught:
                self.installer.change_config(new, 'LocalSubnet')
        self.assertEqual(self.driver.events[-1], ('configure', self.config.port))
        self.assertEqual(self.driver.events.count('start'), 1)
        self.assertEqual(self.driver.state, 'stopped')
        self.assertIs(caught.exception.__cause__, restore_error)
        self.assertIn('incompleta', str(caught.exception))
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_failed_service_configuration_restore_never_restarts_with_uncertain_state(self):
        from dataclasses import replace
        new = replace(self.config, port=9999)
        original_configure = self.driver.configure
        restore_error = RuntimeError('PRIVATE-SERVICE-RESTORE')
        def configure(installation, config):
            original_configure(installation, config)
            if config.port == self.config.port:
                raise restore_error
        with patch('mockaize_api.windows_ops.wait_health', side_effect=RuntimeError('PRIVATE-HEALTH')), \
                patch.object(self.driver, 'configure', side_effect=configure):
            with self.assertRaises(RuntimeError) as caught:
                self.installer.change_config(new, 'LocalSubnet')
        self.assertEqual(load_config(self.path), self.config)
        self.assertEqual(self.driver.events.count('start'), 1)
        self.assertEqual(self.driver.state, 'stopped')
        self.assertIs(caught.exception.__cause__, restore_error)
        self.assertIn('incompleta', str(caught.exception))

    @unittest.skipUnless(os.name == 'nt', 'Windows ACL inheritance')
    def test_real_input_file_delete_inheritance_changes_without_removing_user_grant(self):
        from dataclasses import replace
        import win32security
        from mockaize_api.config import Cleanup, CleanupRule
        from mockaize_api.windows_ops import _current_user_sid
        directory = self.config.input_directory / 'existing-subdirectory'
        directory.mkdir(parents=True)
        file = directory / 'disposable.xml'
        file.write_bytes(b'disposable')
        user_sid = _current_user_sid()
        def rights(sid):
            descriptor = win32security.GetNamedSecurityInfo(str(file), win32security.SE_FILE_OBJECT,
                                                           win32security.DACL_SECURITY_INFORMATION)
            acl = descriptor.GetSecurityDescriptorDacl()
            return [(acl.GetAce(index)[0][1], acl.GetAce(index)[1]) for index in range(acl.GetAceCount())
                    if win32security.ConvertSidToStringSid(acl.GetAce(index)[2]) == sid]
        driver = WindowsDriver()
        driver.configure_inputs(self.config, self.data)
        initial_user = rights(user_sid)
        self.assertTrue(initial_user)
        self.assertFalse(any(mask & 0x10000 for _, mask in rights('S-1-5-20')))
        enabled = replace(self.config, cleanup=Cleanup(inputs=CleanupRule('age', 7)))
        driver.configure_inputs(enabled, self.data)
        self.assertTrue(any(flags & 0x10 and mask & 0x10000 for flags, mask in rights('S-1-5-20')))
        driver.configure_inputs(self.config, self.data)
        self.assertFalse(any(mask & 0x10000 for _, mask in rights('S-1-5-20')))
        self.assertEqual(rights(user_sid), initial_user)
        self.assertEqual(file.read_bytes(), b'disposable')

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
        self.assertEqual((self.target / UNINSTALL_EXE).read_text(), 'new binary')
        import json
        receipt = json.loads((self.target / 'installation.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['configPath'], str(self.path))
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
        self.assertIn('verify-absent', self.driver.events)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'remove binaries'
                             for event in self.driver.events))

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
