import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('build_verification',
    Path(__file__).resolve().parents[1] / 'packaging' / 'verify_binaries.py')
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


class BuildVerificationTests(unittest.TestCase):
    def valid_names(self):
        return ['payload/MockAiZeApiService.exe', 'payload/MockAiZeApiConfig.exe',
                'payload/MockAiZeApiUninstall.exe', 'payload/_internal/python314.dll',
                'payload/licenses/PYTHON-LICENSE.txt',
                'payload/licenses/Inno-Setup-LICENSE.txt']

    def test_complete_setup_payload_accepts_windows_archive_separators(self):
        verification.validate_payload([name.replace('/', '\\') for name in self.valid_names()])

    def test_setup_without_uninstaller_is_rejected(self):
        names = [name for name in self.valid_names() if 'Uninstall.exe' not in name]
        with self.assertRaises(ValueError):
            verification.validate_payload(names)

    def test_setup_without_bundled_runtime_is_rejected(self):
        names = [name for name in self.valid_names() if '_internal/' not in name]
        with self.assertRaises(ValueError):
            verification.validate_payload(names)

    def test_planning_credentials_and_database_never_enter_setup(self):
        for name in ['payload/credentials.json', 'initial-api-docs/history.md',
                     'payload/config.json', 'payload/client.sqlite3', '../escape.exe']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                verification.validate_payload(self.valid_names() + [name])

    def test_qt_and_optional_tls_are_not_in_the_native_distribution(self):
        for name in ['payload/_internal/PySide6/Qt6Core.dll',
                     'payload/_internal/shiboken6/Shiboken.pyd',
                     'payload/_internal/libcrypto-3.dll', 'payload/_internal/_ssl.pyd',
                     'payload/_internal/pythonwin/win32ui.pyd']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                verification.validate_payload(self.valid_names() + [name])

    def test_duplicate_python_runtime_is_rejected(self):
        with self.assertRaises(ValueError):
            verification.validate_payload(self.valid_names() + ['payload/extra/python314.dll'])

    def test_package_copyright_files_are_not_mistaken_for_gui_binaries(self):
        verification.validate_payload(self.valid_names() + ['payload/licenses/pywin32/pythonwin/License.txt'])
