from pathlib import Path
root = Path(SPECPATH).parent
payload = root / 'build' / 'payload'
if not (payload / 'MockAiZeApiService.exe').is_file():
    raise RuntimeError('Execute packaging/build.ps1 primeiro para preparar o payload.')
a = Analysis([str(root / 'packaging' / 'setup_entry.py')], pathex=[str(root / 'src')],
             datas=[(str(payload), 'payload')],
             hiddenimports=['win32timezone', 'win32serviceutil', 'win32com.client'],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MockAiZe-API-Setup',
          console=False, uac_admin=True)
