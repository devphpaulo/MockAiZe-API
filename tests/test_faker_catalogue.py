import json
from pathlib import Path
import unittest
from mockaize_api import faker_catalog

class CatalogueTests(unittest.TestCase):
    def test_manifest_matches_site_fixture(self):
        expected = json.loads((Path(__file__).parent / 'fixtures/faker-manifest-v1.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(faker_catalog.manifest(), expected)
        self.assertEqual(len(expected['categories']), 15)
        self.assertNotIn('currency', [category['id'] for category in expected['categories']])

    def test_every_site_id_generates_text(self):
        manifest = faker_catalog.manifest()
        ids = [item['id'] for category in manifest['categories'] for item in category['items']]
        ids += [item['id'] for item in manifest['legacyItems']]
        for catalog_id in ids:
            with self.subTest(catalog_id=catalog_id):
                value = faker_catalog.generate({'type':'faker','catalogVersion':1,'catalogId':catalog_id})['value']
                self.assertIsInstance(value, str)
