from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fixtures.catalog_factory import create_catalog
from mockaize_api.catalog import Catalog
from mockaize_api.errors import ApiError
from mockaize_api.preset_codec import decode_preset, encode_preset
from mockaize_api.preset_repository import PresetRepository


FIXTURES = Path(__file__).parent / 'fixtures' / 'preset-v1'


def _journal(*, catalog_wide=False, affected=('fixture-1',)):
    return {'schemaVersion': 1, 'operationId': str(uuid.uuid4()), 'rootId': str(uuid.uuid4()),
            'kind': 'batch', 'catalogWide': catalog_wide, 'affectedIds': sorted(affected),
            'createdAt': datetime.now(timezone.utc).isoformat(), 'files': []}


class PresetRepositoryTests(unittest.TestCase):
    def test_unpublished_temporary_is_ignored_with_windows_casing(self):
        sync = self.root / '.sync'
        sync.mkdir()
        path = sync / (str(uuid.uuid4()).upper() + '.PENDING.JSON.tmp')
        path.write_bytes(b'incomplete unpublished journal')
        self.assertFalse(self.repository.pending())
        self.assertEqual(set(self.repository.scan()['items']), {'fixture-1'})
        self.assertTrue(path.exists())  # The API remains read-only.

    def test_fallback_checks_a_journal_published_during_the_database_read(self):
        database = self.root.parent / 'source.sqlite3'
        create_catalog(database)
        catalog = Catalog(database, self.root)
        original = catalog._database_snapshot
        def read_and_publish(identifier):
            result = original(identifier)
            sync = self.root / '.sync'
            sync.mkdir()
            journal = _journal(affected=('file-1',))
            (sync / (journal['operationId'] + '.pending.json')).write_text(json.dumps(journal), encoding='utf-8')
            return result
        with patch.object(catalog, '_database_snapshot', side_effect=read_and_publish):
            self.assert_api_error('PRESET_SYNC_PENDING', lambda: catalog.snapshot('file-1'))

    def test_fallback_rejects_a_tombstone_completed_during_the_database_read(self):
        database = self.root.parent / 'source.sqlite3'
        create_catalog(database)
        catalog = Catalog(database, self.root)
        original = catalog._database_snapshot
        def read_and_delete(identifier):
            result = original(identifier)
            payload = decode_preset(self.current_path.read_bytes())
            payload['metadata'].update(id=identifier, active=False)
            (self.root / (identifier + '.mockaize.xml')).write_bytes(encode_preset(**payload))
            return result
        with patch.object(catalog, '_database_snapshot', side_effect=read_and_delete):
            self.assert_api_error('PRESET_SYNC_PENDING', lambda: catalog.snapshot('file-1'))
        with self.assertRaises(ApiError) as caught:
            catalog.snapshot('file-1')
        self.assertEqual(caught.exception.code, 'FILE_NOT_FOUND')

    def test_listing_rejects_publication_completed_while_reading_database(self):
        database = self.root.parent / 'source.sqlite3'
        create_catalog(database)
        catalog = Catalog(database, self.root)
        original = catalog._visible_nodes
        def read_and_publish(connection):
            nodes = original(connection)
            payload = decode_preset(self.current_path.read_bytes())
            payload['metadata']['active'] = False
            self.current_path.write_bytes(encode_preset(**payload))
            return nodes
        with patch.object(catalog, '_visible_nodes', side_effect=read_and_publish):
            self.assert_api_error('PRESET_SYNC_PENDING', catalog.files)

    def test_database_fallback_preserves_the_desktop_time_zone(self):
        database = self.root.parent / 'source.sqlite3'
        create_catalog(database)
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute('CREATE TABLE user_settings(key TEXT PRIMARY KEY, value_json TEXT)')
            connection.execute('INSERT INTO user_settings VALUES(?,?)', ('timeZone', json.dumps('Asia/Tokyo')))
        self.assertEqual(Catalog(database, self.root).snapshot('file-1')['context']['timeZone'], 'Asia/Tokyo')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'Presets'
        self.root.mkdir()
        self.current_path = self.root / 'fixture-1.mockaize.xml'
        self.current_path.write_bytes((FIXTURES / 'minimal.mockaize.xml').read_bytes())
        self.repository = PresetRepository(self.root)

    def assert_api_error(self, code, callback):
        with self.assertRaises(ApiError) as caught:
            callback()
        self.assertEqual((caught.exception.status, caught.exception.code), (503, code))

    def test_reads_current_on_each_call_and_ignores_old(self):
        old = self.root / 'fixture-1.OLD.mockaize.xml'
        old.write_bytes(b'not a current preset')
        self.assertTrue(self.repository.available())
        available, payload, inaccessible = self.repository.current('fixture-1')
        self.assertTrue(available)
        self.assertFalse(inaccessible)
        self.assertEqual(payload['metadata']['revision'], 1)
        scan = self.repository.scan()
        self.assertEqual(set(scan['items']), {'fixture-1'})
        payload['metadata']['revision'] = 2
        self.current_path.write_bytes(encode_preset(**payload))
        self.assertEqual(self.repository.current('fixture-1')[1]['metadata']['revision'], 2)

    def test_invalid_current_and_filename_mismatch_fail_as_invalid(self):
        self.current_path.write_bytes(b'<not xml>')
        self.assert_api_error('PRESET_INVALID', lambda: self.repository.current('fixture-1'))
        self.current_path.unlink()
        (self.root / 'other.mockaize.xml').write_bytes((FIXTURES / 'minimal.mockaize.xml').read_bytes())
        self.assert_api_error('PRESET_INVALID', self.repository.scan)

    def test_published_journal_blocks_only_affected_id_or_whole_catalog(self):
        sync = self.root / '.sync'
        sync.mkdir()
        journal = _journal()
        path = sync / (journal['operationId'] + '.pending.json')
        path.write_text(json.dumps(journal), encoding='utf-8')
        self.assertTrue(self.repository.pending('fixture-1'))
        self.assertFalse(self.repository.pending('other'))
        self.assert_api_error('PRESET_SYNC_PENDING', lambda: self.repository.current('fixture-1'))
        journal['catalogWide'] = True
        path.write_text(json.dumps(journal), encoding='utf-8')
        self.assertTrue(self.repository.pending('other'))

    def test_site_journal_can_cover_current_and_old_for_the_same_variation(self):
        sync = self.root / '.sync'
        sync.mkdir()
        journal = _journal()
        journal['files'] = []
        for suffix in ('.mockaize.xml', '.OLD.mockaize.xml'):
            entry = {'final': 'fixture-1' + suffix,
                     'before': {'exists': False}, 'after': {'exists': False}}
            journal['files'].append(entry)
        path = sync / (journal['operationId'] + '.pending.json')
        path.write_text(json.dumps(journal), encoding='utf-8')
        self.assertTrue(self.repository.pending('fixture-1'))
        self.assert_api_error('PRESET_SYNC_PENDING', lambda: self.repository.current('fixture-1'))

    def test_unpublished_journal_temp_is_ignored_but_unknown_sync_entry_fails_closed(self):
        sync = self.root / '.sync'
        sync.mkdir()
        (sync / (str(uuid.uuid4()) + '.pending.json.tmp')).write_bytes(b'incomplete')
        self.assertFalse(self.repository.pending())
        (sync / 'unexpected.txt').write_text('x', encoding='utf-8')
        self.assert_api_error('PRESET_SYNC_UNAVAILABLE', self.repository.pending)

    def test_xml_first_database_fallback_tombstone_and_invalid_no_fallback(self):
        database = self.root.parent / 'source.sqlite3'
        create_catalog(database)
        catalog = Catalog(database, self.root)
        fallback = catalog.snapshot('file-1')
        self.assertEqual(fallback['source'], 'database')
        self.assertEqual(fallback['revision'], 7)

        payload = decode_preset((FIXTURES / 'minimal.mockaize.xml').read_bytes())
        payload['metadata'].update(id='file-1', name='XML name', libraryPath='XML parent', revision=12)
        file_path = self.root / 'file-1.mockaize.xml'
        file_path.write_bytes(encode_preset(**payload))
        snapshot = catalog.snapshot('file-1')
        self.assertEqual((snapshot['source'], snapshot['name'], snapshot['revision']), ('preset', 'XML name', 12))
        payload['metadata']['active'] = False
        file_path.write_bytes(encode_preset(**payload))
        with self.assertRaises(ApiError) as caught:
            catalog.snapshot('file-1')
        self.assertEqual(caught.exception.code, 'FILE_NOT_FOUND')
        self.assertNotIn('file-1', [item['id'] for item in catalog.files()['items']])
        file_path.write_bytes(b'<invalid>')
        with self.assertRaises(ApiError) as caught:
            catalog.snapshot('file-1')
        self.assertEqual(caught.exception.code, 'PRESET_INVALID')

    def test_xml_only_source_survives_missing_database_and_empty_catalog_is_consultable(self):
        missing = self.root.parent / 'missing.sqlite3'
        catalog = Catalog(missing, self.root)
        catalog.preflight()
        catalog.check()
        self.assertEqual(catalog.snapshot('fixture-1')['source'], 'preset')
        self.current_path.unlink()
        self.assertEqual(catalog.files()['items'], [])
        with self.assertRaises(ApiError) as caught:
            catalog.snapshot('absent')
        self.assertEqual(caught.exception.code, 'FILE_NOT_FOUND')

    def test_no_sources_is_unavailable_and_a_current_pending_does_not_block_other_id(self):
        missing = self.root.parent / 'missing.sqlite3'
        self.root.rename(self.root.parent / 'Presets-moved')
        catalog = Catalog(missing, self.root)
        with self.assertRaises(ApiError) as caught:
            catalog.preflight()
        self.assertEqual(caught.exception.code, 'DEPENDENCY_UNAVAILABLE')

        moved = self.root.parent / 'Presets-moved'
        moved.rename(self.root)
        sync = self.root / '.sync'
        sync.mkdir()
        journal = _journal()
        (sync / (journal['operationId'] + '.pending.json')).write_text(json.dumps(journal), encoding='utf-8')
        database = self.root.parent / 'source.sqlite3'
        create_catalog(database)
        catalog = Catalog(database, self.root)
        self.assertEqual(catalog.snapshot('file-1')['source'], 'database')
        self.assert_api_error('PRESET_SYNC_PENDING', catalog.files)

    def assert_api_error(self, code, callback):
        with self.assertRaises(ApiError) as caught:
            callback()
        self.assertEqual((caught.exception.status, caught.exception.code), (503, code))


if __name__ == '__main__':
    unittest.main()
