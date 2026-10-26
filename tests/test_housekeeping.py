from dataclasses import replace
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from mockaize_api.config import ApiConfig, Cleanup, CleanupRule, ConfigurationError
from mockaize_api.housekeeping import FileActivity, Housekeeping
from mockaize_api.policy import Policy
from mockaize_api.request_log import RequestLog


class HousekeepingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('input', 'output', 'logs'):
            (self.root / name).mkdir()
        self.config_path = self.root / 'config.json'
        self.config = ApiConfig(self.root / 'source.sqlite3', self.root / 'input',
                                self.root / 'output', self.root / 'logs', 6578, '127.0.0.1', 'N',
                                cleanup=Cleanup(CleanupRule('age', 2), CleanupRule('age', 2),
                                                CleanupRule('age', 2)))
        self.policy = Policy().resolve(self.config, config_path=self.config_path)
        self.log = Mock()
        self.activity = FileActivity()

    def file(self, name, days=3, hour=12):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'disposable')
        target = date(2026, 10, 26) - timedelta(days=days)
        timestamp = datetime.combine(target, datetime.min.time()).replace(hour=hour).timestamp()
        os.utime(path, (timestamp, timestamp))
        return path

    def cleaner(self, **options):
        values = dict(activity=self.activity, today=date(2026, 10, 26), retry_seconds=0.01)
        values.update(options)
        cleaner = Housekeeping(self.config, self.policy, self.config_path, self.log, **values)
        self.addCleanup(cleaner.stop)
        return cleaner

    def finish(self, cleaner):
        cleaner.start()
        self.assertTrue(cleaner.finished.wait(3), cleaner.counts)
        self.assertTrue(cleaner.stop())

    def test_cutoff_is_local_date_strict_and_recursive_for_all_extensions(self):
        old = [self.file('input/nested/from-user.bin'), self.file('output/x.any', hour=0),
               self.file('logs/arbitrary.backup', hour=23)]
        preserved = [self.file('input/on-cutoff.xml', days=2, hour=0),
                     self.file('output/on-cutoff.txt', days=2, hour=23),
                     self.file('logs/new.dat', days=1)]
        self.finish(self.cleaner())
        self.assertTrue(all(not path.exists() for path in old))
        self.assertTrue(all(path.exists() for path in preserved))
        self.assertTrue((self.root / 'input/nested').is_dir())

    def test_inputs_outputs_disabled_by_default_and_log_write_never_cleans(self):
        self.config = replace(self.config, cleanup=Cleanup())
        self.policy = Policy(logs_retention_days=2).resolve(self.config, config_path=self.config_path)
        input_file = self.file('input/old.xml')
        output_file = self.file('output/old.xml')
        log_file = self.file('logs/old.any')
        self.finish(self.cleaner())
        self.assertTrue(input_file.exists())
        self.assertTrue(output_file.exists())
        self.assertFalse(log_file.exists())
        old = self.file('logs/mockaize-api-logs-01012000.txt')
        RequestLog(self.config.logs_directory, 1).write(method='GET', route='/health', status=200)
        self.assertTrue(old.exists())

    def test_a_worker_runs_once_even_after_new_log_or_file_writes(self):
        cleaner = self.cleaner()
        self.finish(cleaner)
        later = self.file('output/arrived-after-round.xml')
        self.assertFalse(cleaner.start())
        self.assertTrue(later.exists())
        events = [call.kwargs['event'] for call in self.log.write.call_args_list]
        self.assertEqual(events.count('HOUSEKEEPING_STARTED'), 1)
        self.assertEqual(events.count('HOUSEKEEPING_COMPLETED'), 1)

    def test_huge_retention_never_overflows_or_selects_files(self):
        self.config = replace(self.config, cleanup=Cleanup(outputs=CleanupRule('age', 10 ** 100),
                                                         logs=CleanupRule()))
        self.policy = Policy().resolve(self.config, config_path=self.config_path)
        old = self.file('output/old.xml')
        self.finish(self.cleaner())
        self.assertTrue(old.exists())

    def test_transient_cleanup_io_in_constructor_is_retried_without_failing_startup(self):
        import mockaize_api.housekeeping as housekeeping
        old = self.file('output/old.xml')
        actual = housekeeping._no_reparse
        failures = []
        def unavailable_then_ready(path):
            if path == self.config.output_directory and len(failures) < 2:
                failures.append(1)
                raise PermissionError
            return actual(path)
        with patch('mockaize_api.housekeeping._no_reparse', side_effect=unavailable_then_ready):
            cleaner = self.cleaner()
            self.finish(cleaner)
        self.assertEqual(len(failures), 2)
        self.assertFalse(old.exists())
        self.assertGreaterEqual(cleaner.counts['attempts'], 2)

    def test_protected_state_sidecars_and_presets_cannot_be_cleanup_roots(self):
        for protected in (self.config_path.parent / 'api-state.sqlite3-wal',
                          Path(str(self.config.database_path) + '-shm'), self.config.presets_directory):
            config = replace(self.config, output_directory=protected, cleanup=Cleanup(outputs=CleanupRule('age', 2),
                                                                                   logs=CleanupRule()))
            with self.subTest(protected=protected.name), self.assertRaises(ConfigurationError):
                Housekeeping(config, self.policy, self.config_path, self.log)

    def test_junction_and_outside_sentinel_are_not_followed(self):
        if os.name != 'nt':
            self.skipTest('Windows junction behavior')
        outside = self.root / 'outside'
        outside.mkdir()
        sentinel = self.file('outside/sentinel.any')
        junction = self.root / 'output/junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.finish(self.cleaner())
        self.assertTrue(sentinel.exists())
        self.assertTrue(junction.exists())

    def test_root_link_is_rejected_before_worker_starts(self):
        outside = self.root / 'outside'
        outside.mkdir()
        link = self.root / 'linked-output'
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            os.symlink(outside, link, target_is_directory=True)
        config = replace(self.config, output_directory=link)
        with self.assertRaises(ConfigurationError):
            Housekeeping(config, self.policy, self.config_path, self.log)

    def test_opened_handle_outside_root_is_rejected_before_deletion(self):
        inside = self.file('output/old.xml')
        sentinel = self.file('outside/sentinel.any')
        cleaner = self.cleaner()
        with patch('mockaize_api.housekeeping._opened_path', return_value=sentinel), \
                patch('mockaize_api.housekeeping._windows_dispose') as dispose:
            self.finish(cleaner)
        dispose.assert_not_called()
        self.assertTrue(inside.exists())
        self.assertTrue(sentinel.exists())

    def test_windows_junction_swap_opens_outside_handle_but_never_marks_it_for_deletion(self):
        if os.name != 'nt':
            self.skipTest('Windows handle and junction semantics')
        import mockaize_api.housekeeping as housekeeping
        inside = self.file('output/nested/sentinel.any')
        sentinel = self.file('outside/sentinel.any')
        directory = inside.parent
        backup = self.root / 'output/preserved-original'
        outside = sentinel.parent
        actual = housekeeping._delete_stream
        @contextmanager
        def swapped(path):
            self.assertTrue(directory.resolve().is_relative_to(self.root.resolve()))
            self.assertTrue(backup.resolve().is_relative_to(self.root.resolve()))
            directory.rename(backup)
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(directory), str(outside)],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr)
            with actual(path) as stream:
                yield stream
        cleaner = self.cleaner()
        with patch('mockaize_api.housekeeping._delete_stream', side_effect=swapped), \
                patch('mockaize_api.housekeeping._windows_dispose') as dispose:
            self.finish(cleaner)
        dispose.assert_not_called()
        self.assertTrue(sentinel.exists())
        self.assertTrue((backup / 'sentinel.any').exists())

    def test_permission_failure_retries_same_round_and_stop_cancels_backoff(self):
        import mockaize_api.housekeeping as housekeeping
        old = self.file('output/old.xml')
        actual = housekeeping._delete_file
        attempts = []
        def locked_once(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise PermissionError
            return actual(*args, **kwargs)
        with patch('mockaize_api.housekeeping._delete_file', side_effect=locked_once):
            self.finish(self.cleaner())
        self.assertGreaterEqual(len(attempts), 2)
        self.assertFalse(old.exists())
        old = self.file('output/locked.xml')
        reached = threading.Event()
        def always_locked(*args, **kwargs):
            reached.set()
            raise PermissionError
        with patch('mockaize_api.housekeeping._delete_file', side_effect=always_locked):
            cleaner = self.cleaner(retry_seconds=30)
            cleaner.start()
            self.assertTrue(reached.wait(2))
            self.assertTrue(cleaner.stop(timeout=1))
        self.assertTrue(old.exists())

    def test_windows_open_file_is_retried_after_reader_closes_without_force(self):
        if os.name != 'nt':
            self.skipTest('Windows sharing semantics')
        old = self.file('output/locked-by-reader.xml')
        cleaner = self.cleaner()
        with old.open('rb') as reader:
            cleaner.start()
            self.assertFalse(cleaner.finished.wait(0.05))
            self.assertEqual(reader.read(), b'disposable')
            self.assertTrue(old.exists())
        self.assertTrue(cleaner.finished.wait(3), cleaner.counts)
        self.assertFalse(old.exists())

    def test_generation_activity_defers_deletion_without_holding_filesystem_lock(self):
        old = self.file('output/old.xml')
        cleaner = self.cleaner()
        with self.activity.generation():
            cleaner.start()
            self.assertFalse(cleaner.finished.wait(0.05))
            self.assertTrue(old.exists())
        self.assertTrue(cleaner.finished.wait(2))
        self.assertFalse(old.exists())

    def test_blocked_scan_has_bounded_shutdown_and_does_not_leak_after_release(self):
        reached, release = threading.Event(), threading.Event()
        cleaner = self.cleaner()
        def blocked(*args):
            reached.set()
            release.wait(3)
            return False
        with patch.object(cleaner, '_scan_root', side_effect=blocked):
            cleaner.start()
            self.assertTrue(reached.wait(2))
            self.assertFalse(cleaner.stop(timeout=0.01))
            release.set()
            self.assertTrue(cleaner.finished.wait(2))

    def test_cleanup_events_do_not_include_paths_or_payloads(self):
        self.file('output/private.xml')
        self.finish(self.cleaner())
        text = str(self.log.write.call_args_list)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn('private.xml', text)
        self.assertNotIn('disposable', text)
from contextlib import contextmanager
