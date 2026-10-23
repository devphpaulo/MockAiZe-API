from pathlib import Path
root = Path(SPECPATH).parent
a = Analysis([str(root / 'packaging' / 'setup_entry.py')], pathex=[str(root / 'src')],
             hiddenimports=['win32timezone', 'win32serviceutil', 'win32com.client'],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='MockAiZeApiConfig',
          console=False, uac_admin=True)
