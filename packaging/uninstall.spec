from pathlib import Path
root = Path(SPECPATH).parent
assets = root / 'src' / 'mockaize_api' / 'assets'
a = Analysis([str(root / 'packaging' / 'uninstall_entry.py')], pathex=[str(root / 'src')],
             datas=[(str(assets / 'mockaize-favicon.png'), 'mockaize_api/assets')],
             hiddenimports=['win32timezone', 'win32serviceutil', 'win32com.client'],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MockAiZeApiUninstall',
          icon=str(assets / 'mockaize.ico'), console=False, uac_admin=True)
