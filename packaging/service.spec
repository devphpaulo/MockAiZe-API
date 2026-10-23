# Build from the repository root: pyinstaller --noconfirm packaging/service.spec
from pathlib import Path
root = Path(SPECPATH).parent
a = Analysis([str(root / 'packaging' / 'service_entry.py')], pathex=[str(root / 'src')],
             hiddenimports=['win32timezone', 'servicemanager', 'win32serviceutil',
                            'win32service', 'win32event', 'pywintypes',
                            'mockaize_api.runtime', 'mockaize_api.xml_engine',
                            'mockaize_api.formulas'],
             excludes=['PySide6', 'tkinter'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MockAiZeApiService',
          console=False, contents_directory='_internal')
coll = COLLECT(exe, a.binaries, a.datas, name='MockAiZeApiService')
