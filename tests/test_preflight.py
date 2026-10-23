from dataclasses import replace
from contextlib import closing
from unittest.mock import patch
from pathlib import Path
import socket
import sqlite3
import tempfile
import unittest

from mockaize_api.config import ApiConfig
from mockaize_api.preflight import PreflightError, check_environment


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root / 'source.sqlite3'
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute('CREATE TABLE example (value TEXT)')
        for name in ['input', 'output', 'logs']:
            (self.root / name).mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.port = listener.getsockname()[1]
        self.config = ApiConfig(self.database, self.root / 'input', self.root / 'output',
                                self.root / 'logs', self.port, '127.0.0.1', 'N')

    def test_valid_environment_leaves_no_probe_files_and_source_unchanged(self):
        before = self.database.read_bytes()
        check_environment(self.config)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(list(self.config.output_directory.iterdir()), [])
        self.assertEqual(list(self.config.logs_directory.iterdir()), [])

    def test_missing_database_is_never_created(self):
        missing = self.root / 'missing.sqlite3'
        with self.assertRaises(PreflightError):
            check_environment(replace(self.config, database_path=missing))
        self.assertFalse(missing.exists())

    def test_non_sqlite_file_is_rejected(self):
        self.database.write_text('not a database')
        with self.assertRaises(PreflightError):
            check_environment(self.config)

    def test_missing_output_directory_is_not_created(self):
        missing = self.root / 'missing'
        with self.assertRaises(PreflightError):
            check_environment(replace(self.config, output_directory=missing))
        self.assertFalse(missing.exists())

    def test_occupied_port_fails_with_safe_diagnostic(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', self.port))
            listener.listen()
            with self.assertRaises(PreflightError) as error:
                check_environment(self.config)
        self.assertEqual(error.exception.field, 'port')
        self.assertNotIn(str(self.root), str(error.exception))

    def test_unwritable_output_directory_fails(self):
        with patch('mockaize_api.preflight.tempfile.TemporaryFile', side_effect=PermissionError):
            with self.assertRaises(PreflightError) as error:
                check_environment(self.config)
        self.assertEqual(error.exception.field, 'outputDirectory')

    def test_uncheckpointed_wal_database_is_readable(self):
        with closing(sqlite3.connect(self.database)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('INSERT INTO example VALUES (?)', ('saved',))
            writer.commit()
            check_environment(self.config)
