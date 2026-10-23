from pathlib import Path
import tempfile
import unittest

from mockaize_api.setup_ui import detect_mode
from mockaize_api.windows_ops import Installation, CONFIG_EXE, SERVICE_EXE


class Driver:
    def __init__(self, state):
        self.state = state

    def status(self):
        return self.state


class SetupDetectionTests(unittest.TestCase):
    def test_new_installation_is_automatically_detected(self):
        self.assertEqual(detect_mode(None, Driver('absent')), 'new')

    def test_existing_service_and_complete_files_detect_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in ('config.json', SERVICE_EXE, CONFIG_EXE):
                (root / filename).touch()
            installation = Installation(root, root / 'config.json')
            self.assertEqual(detect_mode(installation, Driver('running')), 'update')
            self.assertEqual(detect_mode(installation, Driver('stopped')), 'update')
            self.assertEqual(detect_mode(installation, Driver('absent')), 'repair')
            (root / SERVICE_EXE).unlink()
            self.assertEqual(detect_mode(installation, Driver('running')), 'repair')
