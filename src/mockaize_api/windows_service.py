"""Windows SCM host. Importable on other platforms for packaging and tests."""
from pathlib import Path
import threading

SERVICE_NAME = 'MockAiZeApi'
REGISTRY_KEY = r'SOFTWARE\MockAiZe\API'


def registered_config() -> Path:
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY) as key:
        value, _ = winreg.QueryValueEx(key, 'ConfigPath')
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeError('O caminho registrado da configuração deve ser absoluto.')
    return path


def dispatch() -> None:
    import servicemanager
    import win32service
    import win32serviceutil

    class ApiService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = 'MockAíZé API'
        _svc_description_ = 'Catálogo e geração XML independente do MockAíZé.'

        def __init__(self, args):
            super().__init__(args)
            self.stopped = threading.Event()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=30000)
            self.stopped.set()

        def SvcDoRun(self):
            from .runtime import serve
            try:
                serve(registered_config(), stop_event=self.stopped)
            except Exception:
                # Do not leak request data, paths or credentials into the Event Log.
                servicemanager.LogErrorMsg('MockAiZeApi: falha no serviço; consulte os logs operacionais.')
                self.ReportServiceStatus(win32service.SERVICE_STOPPED, win32ExitCode=1066,
                                         svcExitCode=1)
                raise

    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(ApiService)
    servicemanager.StartServiceCtrlDispatcher()
