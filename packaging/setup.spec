from pathlib import Path
root = Path(SPECPATH).parent
payload = root / 'build' / 'payload'
if not all((payload / name).is_file() for name in ('MockAiZeApiService.exe', 'MockAiZeApiConfig.exe', 'MockAiZeApiUninstall.exe')):
    raise RuntimeError('Execute packaging/build.ps1 primeiro para preparar o payload.')
a = Analysis([str(root / 'packaging' / 'setup_entry.py')], pathex=[str(root / 'src')],
             datas=[(str(payload), 'payload'), (str(root / 'src/mockaize_api/assets/mockaize-favicon.png'), 'mockaize_api/assets')],
             hiddenimports=['win32timezone', 'win32serviceutil', 'win32com.client'],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MockAiZe-API-Setup',
          icon=str(root / 'src/mockaize_api/assets/mockaize.ico'), console=False, uac_admin=True)
