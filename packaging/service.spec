# Build from the repository root: pyinstaller --noconfirm packaging/service.spec
from pathlib import Path
root = Path(SPECPATH).parent
a = Analysis([str(root / 'packaging' / 'service_entry.py')], pathex=[str(root / 'src')],
             hiddenimports=['win32timezone', 'servicemanager', 'win32serviceutil',
                            'win32service', 'win32event', 'pywintypes',
                            'mockaize_api.runtime', 'mockaize_api.xml_engine',
                            'mockaize_api.formulas', 'mockaize_api.maintenance',
                            'win32com.client', 'pythoncom', '_sha2', '_sha1', '_md5', '_sha3', '_blake2'],
             # Supported API transport is HTTP. Built-in C hash modules provide
             # the same SHA-256/HMAC algorithms without bundling unused TLS/OpenSSL.
             excludes=['PySide6', 'shiboken6', 'tkinter', 'ssl', '_ssl', '_hashlib'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MockAiZeApiService',
          icon=str(root / 'src/mockaize_api/assets/mockaize.ico'), console=False, upx=False, contents_directory='_internal')
coll = COLLECT(exe, a.binaries, a.datas, name='MockAiZeApiService')
