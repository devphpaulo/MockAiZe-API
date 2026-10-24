from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mockaize_api.windows_service import dispatch


class DispatcherError(Exception):
    def __init__(self, code):
        self.winerror = code
        super().__init__(code, 'StartServiceCtrlDispatcher', 'Windows error')


class ServiceDispatchTests(unittest.TestCase):
    def dispatch_with(self, error=None):
        manager = SimpleNamespace(Initialize=Mock(), PrepareToHostSingle=Mock(),
                                  StartServiceCtrlDispatcher=Mock(side_effect=error))
        modules = {'servicemanager': manager, 'win32service': SimpleNamespace(),
                   'win32serviceutil': SimpleNamespace(ServiceFramework=object),
                   'pywintypes': SimpleNamespace(error=DispatcherError)}
        return manager, patch.dict('sys.modules', modules)

    def test_opened_manually_shows_help_without_a_traceback(self):
        manager, modules = self.dispatch_with(DispatcherError(1063))
        with modules, patch('mockaize_api.windows_service.show_interactive_help') as help_message:
            dispatch()
        manager.StartServiceCtrlDispatcher.assert_called_once_with()
        help_message.assert_called_once_with()

    def test_service_manager_start_does_not_show_interactive_help(self):
        manager, modules = self.dispatch_with()
        with modules, patch('mockaize_api.windows_service.show_interactive_help') as help_message:
            dispatch()
        manager.PrepareToHostSingle.assert_called_once()
        help_message.assert_not_called()

    def test_other_windows_errors_are_not_hidden(self):
        error = DispatcherError(5)
        _, modules = self.dispatch_with(error)
        with modules, patch('mockaize_api.windows_service.show_interactive_help') as help_message:
            with self.assertRaises(DispatcherError) as caught:
                dispatch()
        self.assertIs(caught.exception, error)
        help_message.assert_not_called()
