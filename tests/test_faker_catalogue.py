import json
import re
from pathlib import Path
import unittest
from mockaize_api import faker_catalog

class CatalogueTests(unittest.TestCase):
    def test_manifest_matches_site_fixture(self):
        expected = json.loads((Path(__file__).parent / 'fixtures/faker-manifest-v1.json').read_text(encoding='utf-8-sig'))
        actual = faker_catalog.manifest()
        # inspect renders equivalent typing annotations differently across Python versions.
        for manifest in (actual, expected):
            for category in manifest['categories']:
                for item in category['items']:
                    item.pop('returnAnnotation', None)
                    for parameter in item['providerParameters']:
                        parameter.pop('annotation', None)
                        default = parameter.get('default')
                        # Faker binds some date defaults at provider import time.
                        if isinstance(default, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', default):
                            parameter['default'] = '<provider-date>'
        self.assertEqual(actual, expected)
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
