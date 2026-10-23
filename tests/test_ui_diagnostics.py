import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from mockaize_api import ui_diagnostics


class UiDiagnosticDispatchTests(unittest.TestCase):
    def test_regular_startup_still_calls_the_application(self):
        main = Mock()
        with patch.object(sys, 'argv', ['app.exe']):
            ui_diagnostics.dispatch(main)
        main.assert_called_once_with()

    def test_diagnostic_never_starts_installation_or_uninstallation(self):
        main = Mock()
        with patch.object(sys, 'argv', ['app.exe', '--diagnose-ui', 'report.json']), \
                patch.object(ui_diagnostics, 'check_ui', return_value=1) as check:
            with self.assertRaises(SystemExit) as result:
                ui_diagnostics.dispatch(main)
        self.assertEqual(result.exception.code, 1)
        check.assert_called_once_with(Path('report.json'))
        main.assert_not_called()

    def test_missing_report_argument_does_not_start_the_application(self):
        main = Mock()
        with patch.object(sys, 'argv', ['app.exe', '--diagnose-ui']), self.assertRaises(SystemExit):
            ui_diagnostics.dispatch(main)
        main.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Qt não instalado')
    def test_real_qt_window_and_icon_load_without_touching_windows_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.json'
            environment = {name: value for name, value in os.environ.items()
                           if not name.upper().startswith(('QT_', 'QML'))}
            process = subprocess.run([sys.executable, '-m', 'mockaize_api.ui_diagnostics', str(report)],
                                     env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(result['status'], 'passed')
            self.assertTrue(result['iconLoaded'])
            self.assertEqual(result['installationChanged'], False)
            if os.name == 'nt':
                self.assertEqual(result['platform'], 'windows')
