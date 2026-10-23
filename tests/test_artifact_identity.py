import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('inspect_artifact',
    Path(__file__).resolve().parents[1] / 'packaging' / 'inspect_artifact.py')
inspection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspection)


class ArtifactIdentityTests(unittest.TestCase):
    def test_hashes_correspond_to_actual_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample'
            path.write_bytes(b'abc')
            self.assertEqual(inspection.file_hashes(path), {
                'md5': '900150983cd24fb0d6963f7d28e17f72',
                'sha256': 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'})

    def test_matching_md5_does_not_hide_a_sha256_mismatch(self):
        actual = {'md5': 'a', 'sha256': 'b'}
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            inspection.require_identity(actual, {'md5': 'a', 'sha256': 'c'})

    def test_matching_sha256_does_not_hide_a_different_reported_md5(self):
        actual = {'md5': 'a', 'sha256': 'b'}
        with self.assertRaisesRegex(ValueError, 'MD5'):
            inspection.require_identity(actual, {'md5': 'c', 'sha256': 'b'})

    def test_digest_letter_case_is_irrelevant(self):
        inspection.require_identity({'md5': 'abc', 'sha256': 'def'},
                                    {'md5': 'ABC', 'sha256': 'DEF'})
