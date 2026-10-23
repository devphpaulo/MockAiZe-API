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
                'payload/licenses/free-software-terms/LGPL-3.0.txt',
                'mockaize_api/assets/mockaize-favicon.png']

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
