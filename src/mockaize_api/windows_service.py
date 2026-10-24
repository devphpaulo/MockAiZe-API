"""Windows SCM host. Importable on other platforms for packaging and tests."""
from pathlib import Path
import threading

SERVICE_NAME = 'MockAiZeApi'
REGISTRY_KEY = r'SOFTWARE\MockAiZe\API'


def show_interactive_help() -> None:
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        None,
        'MockAiZeApiService.exe é executado em segundo plano pelo Windows.\n\n'
        'Para usar a API e o Swagger, abra o endereço configurado no navegador.\n'
        'Endereço padrão: http://127.0.0.1:6578/\n\n'
        'Para alterar a configuração, abra MockAiZeApiConfig.exe.\n'
        'Para iniciar ou parar o serviço, abra Serviços do Windows (services.msc) '
        'e procure MockAíZé API.',
        'MockAíZé API — Serviço Windows',
        0x40,  # MB_OK | MB_ICONINFORMATION
    )


def registered_config() -> Path:
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY) as key:
        value, _ = winreg.QueryValueEx(key, 'ConfigPath')
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeError('O caminho registrado da configuração deve ser absoluto.')
    return path


def dispatch() -> None:
    import pywintypes
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
    try:
        servicemanager.StartServiceCtrlDispatcher()
    except pywintypes.error as error:
        if error.winerror != 1063:
            raise
        # SCM starts this process without arguments. Double-clicking the same
        # executable also reaches this branch, but has no SCM connection.
        show_interactive_help()
