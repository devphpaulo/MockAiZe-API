from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fixtures.catalog_factory import create_catalog
from mockaize_api.catalog import Catalog
from mockaize_api.errors import ApiError


class CatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'source.sqlite3'
        create_catalog(self.path)
        self.catalog = Catalog(self.path)

    def assert_error(self, code, callback, status=None):
        with self.assertRaises(ApiError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        if status:
            self.assertEqual(caught.exception.status, status)

    def update_config(self, mutate):
        with closing(sqlite3.connect(self.path)) as db, db:
            config = json.loads(db.execute('SELECT config_json FROM variations').fetchone()[0])
            mutate(config)
            db.execute('UPDATE variations SET config_json=?', (json.dumps(config),))

    def test_snapshot_uses_library_name_and_consistent_revision(self):
        before = hashlib.sha256(self.path.read_bytes()).digest()
        snapshot = self.catalog.snapshot('file-1')
        self.assertEqual((snapshot['name'], snapshot['revision']), ('Sample', 7))
        self.assertEqual(snapshot['libraryPath'], 'Workspace / Examples / Sample')
        self.catalog.check()
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).digest())

    def test_deleted_ancestor_hides_descendant_from_all_operations(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE library_nodes SET deleted_at='today' WHERE id='folder'")
        self.assertEqual(self.catalog.files()['items'], [])
        for method in (self.catalog.snapshot, self.catalog.modes, self.catalog.returns):
            self.assert_error('FILE_NOT_FOUND', lambda: method('file-1'), 404)

    def test_modes_and_returns_ignore_active_mode_and_selection(self):
        self.assertEqual([m['id'] for m in self.catalog.modes('file-1')['items']], ['new', 'return'])
        self.assertTrue(all(m['ready'] for m in self.catalog.modes('file-1')['items']))
        models = self.catalog.returns('file-1')['items']
        self.assertEqual([m['id'] for m in models], ['ret-a', 'ret-b'])
        self.assertTrue(all(m['ready'] for m in models))

    def test_mode_readiness_requires_mode_specific_input_and_existing_group(self):
        self.update_config(lambda c: c['inputByMode']['new'].update(group='[]'))
        modes = self.catalog.modes('file-1')['items']
        self.assertFalse(modes[0]['ready'])
        self.assertTrue(modes[1]['ready'])
        self.update_config(lambda c: c['inputByMode'].pop('return'))
        self.assertFalse(self.catalog.returns('file-1')['items'][0]['ready'])

    def test_invalid_output_model_is_not_ready(self):
        self.update_config(lambda c: c['returnModels'][0].update(outputXml='<!DOCTYPE x><x/>'))
        models = self.catalog.returns('file-1')['items']
        self.assertFalse(models[0]['ready'])
        self.assertTrue(models[1]['ready'])

    def test_filter_cursor_and_stable_name_id_order(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            for identity, name in [('file-2', 'sample'), ('file-3', 'Other')]:
                db.execute('INSERT INTO library_nodes SELECT ?,parent_id,kind,?,NULL,created_at FROM library_nodes WHERE id=?', (identity, name, 'file-1'))
                db.execute('INSERT INTO variations SELECT ?,specific_file_id,?,config_json,file_index,revision,created_at FROM variations WHERE id=?', (identity, name, 'file-1'))
        first = self.catalog.files(q='SAMPLE', limit=1)
        self.assertEqual(first['items'][0]['id'], 'file-1')
        second = self.catalog.files(q='sample', limit=1, cursor=first['nextCursor'])
        self.assertEqual(second['items'][0]['id'], 'file-2')
        self.assertIsNone(second['nextCursor'])
        self.assert_error('INVALID_REQUEST', lambda: self.catalog.files(q='other', cursor=first['nextCursor']), 400)
        for value in ('bad', '', 'e30'):
            self.assert_error('INVALID_REQUEST', lambda: self.catalog.files(cursor=value), 400)
        self.assert_error('INVALID_REQUEST', lambda: self.catalog.files(limit=201), 400)

    def test_unknown_or_incomplete_schema_is_unavailable(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE schema_meta SET value='99'")
        self.assert_error('DEPENDENCY_UNAVAILABLE', self.catalog.check, 503)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE schema_meta SET value='2'")
            db.execute('DROP TABLE library_nodes')
        self.assert_error('DEPENDENCY_UNAVAILABLE', self.catalog.check, 503)

    def test_missing_database_is_not_created(self):
        missing = self.path.parent / 'missing.sqlite3'
        self.assert_error('DEPENDENCY_UNAVAILABLE', Catalog(missing).check, 503)
        self.assertFalse(missing.exists())

    def test_committed_wal_updates_visible_without_mutating_source(self):
        writer = sqlite3.connect(self.path)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute("UPDATE variations SET revision=8 WHERE id='file-1'")
        writer.commit()
        files = [self.path, Path(str(self.path) + '-wal')]
        before = [p.read_bytes() for p in files]
        self.assertEqual(self.catalog.snapshot('file-1')['revision'], 8)
        self.assertEqual(before, [p.read_bytes() for p in files])

    def test_invalid_configuration_fails_without_exposing_content(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE variations SET config_json='private broken data'")
        self.assert_error('DEPENDENCY_UNAVAILABLE', lambda: self.catalog.snapshot('file-1'), 503)

    def test_read_transaction_cannot_write(self):
        with self.assertRaises(ApiError):
            with self.catalog._read() as connection:
                connection.execute('UPDATE variations SET revision=999')
        self.assertEqual(self.catalog.snapshot('file-1')['revision'], 7)

    def test_one_snapshot_keeps_revision_even_when_writer_commits_during_read(self):
        writer = sqlite3.connect(self.path)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        parent = self.catalog

        class ConcurrentCatalog(Catalog):
            @staticmethod
            def _visible_nodes(connection):
                nodes = parent._visible_nodes(connection)
                writer.execute('UPDATE variations SET revision=8')
                writer.commit()
                return nodes

        self.assertEqual(ConcurrentCatalog(self.path).snapshot('file-1')['revision'], 7)
        self.assertEqual(self.catalog.snapshot('file-1')['revision'], 8)

    def test_namespace_groups_and_sibling_indexes_use_expanded_names(self):
        group = json.dumps([{'ns': 'urn:example', 'name': 'Root', 'index': 1},
                            {'ns': 'urn:example', 'name': 'Row', 'index': 2}])
        xml = '<r:Root xmlns:r="urn:example"><r:Row><r:Value/></r:Row><r:Row><r:Value/></r:Row></r:Root>'
        self.update_config(lambda c: c['inputByMode']['new'].update(xml=xml, group=group))
        self.assertTrue(self.catalog.modes('file-1')['items'][0]['ready'])
        self.update_config(lambda c: c['inputByMode']['new'].update(group=group.replace('urn:example', 'urn:wrong')))
        self.assertFalse(self.catalog.modes('file-1')['items'][0]['ready'])

    def test_unreachable_and_cyclic_nodes_are_hidden(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE library_nodes SET parent_id='file-1' WHERE id='folder'")
        self.assertEqual(self.catalog.files()['items'], [])
        self.assert_error('FILE_NOT_FOUND', lambda: self.catalog.snapshot('file-1'), 404)

    def test_model_limit_and_both_schema_markers_are_checked(self):
        self.update_config(lambda c: c.update(returnModels=c['returnModels'] * 11))
        self.assert_error('DEPENDENCY_UNAVAILABLE', lambda: self.catalog.returns('file-1'), 503)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE app_meta SET value='1'")
        self.assert_error('DEPENDENCY_UNAVAILABLE', self.catalog.check, 503)


if __name__ == '__main__':
    unittest.main()
