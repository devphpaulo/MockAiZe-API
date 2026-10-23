"""Exercita as janelas com operações de serviço/limpeza inteiramente simuladas."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch


@unittest.skipUnless(importlib.util.find_spec('PySide6') and importlib.util.find_spec('pythoncom'),
                     'Prévia Qt requer dependências Windows opcionais.')
class UninstallUiTests(unittest.TestCase):
    def test_questions_follow_service_removal_and_ok_finishes(self):
        self.run_flow(False)

    def test_service_failure_shows_error_without_cleanup_questions(self):
        self.run_flow(True)

    def run_flow(self, fail):
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication, QMessageBox
        from mockaize_api.uninstall_ui import main
        from mockaize_api.windows_ops import Installation
        app = QApplication.instance() or QApplication([])
        installation = Installation(Path('C:/Program Files/MockAiZe API'), Path('C:/MockAiZe API/config.json'))
        session = MagicMock()
        session.installation = installation
        session.detached = False
        session.folders = [Path('C:/MockAiZe API')]
        def detach():
            if fail:
                raise RuntimeError('Serviço ainda listado.')
            session.detached = True
        session.detach.side_effect = detach
        session.cleanup.return_value = {'restartRequired': False}
        def ask(*args):
            self.assertTrue(session.detached)
            return QMessageBox.No
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(app.quit)
        watchdog.start(5000)
        try:
            with patch('mockaize_api.uninstall_ui.discover_uninstall_target', return_value=installation), \
                    patch('mockaize_api.uninstall_ui.UninstallSession', return_value=session), \
                    patch.object(QMessageBox, 'question', side_effect=ask) as question, \
                    patch.object(QMessageBox, 'information') as information, \
                    patch.object(QMessageBox, 'critical') as critical:
                main()
                if fail:
                    critical.assert_called_once()
                    question.assert_not_called()
                    information.assert_not_called()
                    session.cleanup.assert_not_called()
                else:
                    critical.assert_not_called()
                    self.assertEqual(question.call_count, 2)
                    session.cleanup.assert_called_once_with(False, [])
                    self.assertIn('OK.', information.call_args.args[2])
        finally:
            watchdog.stop()
