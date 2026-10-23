from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from mockaize_api.errors import ApiError
from mockaize_api.inputs import read_input_file
from mockaize_api.publication import publish, metadata
from mockaize_api.security import create_credentials, verify_key
from mockaize_api.state import State


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_credentials_store_hash_and_rotation_invalidates_previous_key(self):
        config = self.root / 'config.json'
        key = create_credentials(config)
        self.assertTrue(verify_key(config, key))
        self.assertFalse(verify_key(config, 'wrong'))
        self.assertNotIn(key, (self.root / 'credentials.json').read_text())
        with self.assertRaises(ApiError):
            create_credentials(config)
        rotated = create_credentials(config, rotate=True)
        self.assertFalse(verify_key(config, key))
        self.assertTrue(verify_key(config, rotated))

    def test_publication_never_overwrites_and_metadata_covers_utf8(self):
        content = '<raiz>ação</raiz>'.encode()
        original = self.root / 'same.xml'
        original.write_bytes(b'original')
        result = publish(self.root, [{'fileName': 'same.xml', 'content': content}])
        self.assertEqual(original.read_bytes(), b'original')
        self.assertNotEqual(result[0]['fileName'], 'same.xml')
        self.assertEqual((self.root / result[0]['fileName']).read_bytes(), content)
        self.assertEqual(result[0]['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(result[0]['sizeBytes'], len(content))

    def test_partial_publication_compensates_own_outputs(self):
        import os
        actual = os.link
        calls = []
        def link(source, target):
            calls.append(target)
            if len(calls) == 2:
                raise PermissionError
            actual(source, target)
        with patch('mockaize_api.publication.os.link', side_effect=link):
            with self.assertRaises(ApiError):
                publish(self.root, [{'fileName': 'a.xml', 'content': b'<a/>'},
                                    {'fileName': 'b.xml', 'content': b'<b/>'}])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_publication_rejects_unsafe_name_before_any_output(self):
        for name in ['../escape.xml', 'CON.xml', 'sub/path.xml', 'a.xml:stream', 'a.xml ']:
            with self.subTest(name=name), self.assertRaises(ApiError):
                publish(self.root, [{'fileName': name, 'content': b'<a/>'}])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_decimal_size_display(self):
        self.assertEqual(metadata(b'x' * 1234)['sizeDisplay'], '1.23 KB')
        self.assertEqual(metadata(b'x' * 1000000)['sizeDisplay'], '1.00 MB')

    def test_input_directory_boundary_and_size(self):
        folder = self.root / 'allowed'
        folder.mkdir()
        inside = folder / 'entrada.xml'
        inside.write_text('<a/>', encoding='utf-8')
        outside = self.root / 'secret.xml'
        outside.write_text('<secret/>')
        self.assertEqual(read_input_file(folder, str(inside)), '<a/>')
        for value in [str(outside), 'relative.xml', str(folder)]:
            with self.subTest(value=value), self.assertRaises(ApiError):
                read_input_file(folder, value)
        inside.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        with self.assertRaises(ApiError) as error:
            read_input_file(folder, str(inside))
        self.assertEqual(error.exception.status, 413)

    def test_idempotency_replays_exact_bytes_and_conflict(self):
        state = State(self.root / 'state.sqlite3')
        self.assertIsNone(state.begin('new', 'key-1', 'fingerprint'))
        response = {'status': 200, 'headers': {}, 'body': '<raiz>ação</raiz>'.encode()}
        state.complete('new', 'key-1', response)
        self.assertEqual(state.begin('new', 'key-1', 'fingerprint'), response)
        with self.assertRaises(ApiError) as error:
            state.begin('new', 'key-1', 'different')
        self.assertEqual(error.exception.code, 'IDEMPOTENCY_CONFLICT')

    def test_pending_request_is_not_reexecuted_after_restart(self):
        path = self.root / 'state.sqlite3'
        State(path).begin('new', 'pending', 'same')
        with self.assertRaises(ApiError):
            State(path).begin('new', 'pending', 'same')

    def test_retention_never_expires_running_generation(self):
        state = State(self.root / 'state.sqlite3', retention_seconds=60)
        with patch('mockaize_api.state.time.time', return_value=1000):
            state.begin('new', 'pending', 'same')
        with patch('mockaize_api.state.time.time', return_value=1061):
            with self.assertRaises(ApiError):
                state.begin('new', 'pending', 'same')

    def test_cancel_allows_same_key_retry_before_generation(self):
        state = State(self.root / 'state.sqlite3')
        state.begin('new', 'retry', 'same')
        state.cancel('new', 'retry')
        self.assertIsNone(state.begin('new', 'retry', 'same'))

    def test_api_sequences_are_separate_and_persist_across_restart(self):
        path = self.root / 'state.sqlite3'
        self.assertEqual(State(path).next_index('file-1'), 0)
        self.assertEqual(State(path).next_index('file-1'), 1)
        self.assertEqual(State(path).next_index('other'), 0)
