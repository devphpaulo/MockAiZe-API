import importlib.util
import os
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('freeze',
    Path(__file__).resolve().parents[1] / 'packaging' / 'freeze.py')
freeze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze)


class FreezeEnvironmentTests(unittest.TestCase):
    def test_foreign_dll_paths_and_python_qt_overrides_are_not_inherited(self):
        root = Path.cwd().resolve()
        original = {'Path': str(root / 'poppler'), 'PYTHONPATH': str(root / 'external'),
                    'PYTHONHOME': str(root / 'another-python'), 'QT_PLUGIN_PATH': 'foreign',
                    'QML2_IMPORT_PATH': 'foreign', 'QT_QPA_PLATFORM_PLUGIN_PATH': 'foreign',
                    'QT_QPA_PLATFORM': 'offscreen', 'SystemRoot': str(root / 'Windows'),
                    'KEEP_ME': 'value'}
        actual = freeze.isolated_environment(original, root / 'venv/Scripts/python.exe',
                                              root / 'Python', root / 'Windows')
        self.assertNotIn('poppler', actual['PATH'])
        self.assertNotIn('Path', actual)
        for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH',
                     'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM'):
            self.assertNotIn(name, actual)
        self.assertIn(str(root / 'venv/Scripts'), actual['PATH'].split(os.pathsep))
        self.assertIn(str(root / 'Windows/System32'), actual['PATH'].split(os.pathsep))
        self.assertEqual(actual['KEEP_ME'], 'value')
        self.assertEqual(original['QT_PLUGIN_PATH'], 'foreign')

    def test_native_library_from_an_external_tool_is_rejected(self):
        root = Path.cwd().resolve()
        with self.assertRaisesRegex(ValueError, 'icuuc.dll'):
            freeze.validate_native_sources([('icuuc.dll', str(root / 'poppler/icuuc.dll'), 'BINARY')],
                                           [root / 'venv', root / 'Windows'])

    def test_a_similar_prefix_is_not_an_allowed_directory(self):
        root = Path.cwd().resolve()
        with self.assertRaises(ValueError):
            freeze.validate_native_sources([('foreign.dll', str(root / 'venv-foreign/x.dll'), 'BINARY')],
                                           [root / 'venv'])

    def test_libraries_from_runtime_wheel_and_windows_are_allowed(self):
        root = Path.cwd().resolve()
        entries = [('Qt6Core.dll', str(root / 'venv/Lib/site-packages/PySide6/Qt6Core.dll'), 'BINARY'),
                   ('VCRUNTIME140.dll', str(root / 'Python/VCRUNTIME140.dll'), 'BINARY'),
                   ('system.dll', str(root / 'Windows/System32/system.dll'), 'BINARY')]
        freeze.validate_native_sources(entries, [root / 'venv', root / 'Python', root / 'Windows'])
