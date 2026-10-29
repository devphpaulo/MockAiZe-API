"""Executable checks for the documented local contract; no external validator required."""
import json
from pathlib import Path
import tempfile
import unittest

from fixtures.catalog_factory import create_catalog
from mockaize_api.catalog import Catalog
from mockaize_api.errors import ApiError
from mockaize_api.runtime import _problem, validate_generation
from mockaize_api.xml_engine import generate_new, generate_return


ROOT = Path(__file__).resolve().parents[1]


class ContractDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((ROOT / 'src/mockaize_api/assets/swagger/openapi.json').read_text(encoding='utf-8'))

    def test_all_openapi_references_resolve_locally(self):
        def visit(value):
            if isinstance(value, dict):
                if '$ref' in value:
                    reference = value['$ref']
                    self.assertTrue(reference.startswith('#/'))
                    target = self.spec
                    for part in reference[2:].split('/'):
                        target = target[part.replace('~1', '/').replace('~0', '~')]
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(self.spec)

    def test_security_alternatives_and_login_contract_match_authenticator(self):
        self.assertEqual(self.spec['security'], [{'ApiKey': []}, {'Bearer': []}])
        schemes = self.spec['components']['securitySchemes']
        self.assertEqual(schemes['ApiKey']['name'], 'X-API-Key')
        self.assertEqual((schemes['Bearer']['type'], schemes['Bearer']['scheme']), ('http', 'bearer'))
        login = self.spec['paths']['/api/v1/auth/token']['post']
        self.assertEqual(login['security'], [{'ApiKey': []}])
        self.assertEqual(self.spec['paths']['/health']['get']['security'], [])
        token = self.spec['components']['schemas']['TokenResponse']
        self.assertEqual(set(token['required']), {'access_token', 'token_type', 'expires_in'})
        self.assertEqual(token['properties']['expires_in']['enum'], [1800])

    def test_generation_schema_and_every_example_match_real_fixture(self):
        schemas = self.spec['components']['schemas']
        self.assertEqual(set(schemas['ReturnXmlRequest']['required']), {'inputXml', 'returnSelection'})
        self.assertNotIn('inputFilePath', schemas['ReturnXmlRequest']['properties'])
        self.assertNotIn('maximum', schemas['NewXmlRequest']['properties']['recordCount'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.sqlite3'
            create_catalog(path)
            variation = Catalog(path).snapshot('file-1')
            for operation in ('new', 'return'):
                post = self.spec['paths']['/api/v1/files/xml/{fileId}/' + operation]['post']
                examples = post['requestBody']['content']['application/json']['examples']
                for name, example in examples.items():
                    with self.subTest(operation=operation, example=name):
                        payload = example['value']
                        validate_generation(operation, {**payload, 'fileId': 'file-1'})
                        if operation == 'new':
                            result = generate_new(variation, payload['recordCount'])
                        else:
                            result = generate_return(variation, payload['returnSelection'],
                                payload.get('composition', 'apart'), input_xml=payload['inputXml'],
                                input_records=payload.get('inputRecords', 'all'))
                        self.assertTrue(result)
                self.assertIn('410', post['responses'])

    def test_error_schema_matches_runtime_envelope_and_extensions(self):
        schema = self.spec['components']['schemas']['ErrorResponse']
        self.assertEqual(schema['required'], ['error'])
        nested = schema['properties']['error']
        self.assertEqual(set(nested['required']), {'code', 'message', 'traceId'})
        self.assertFalse(nested['additionalProperties'])
        self.assertNotIn('status', schema['properties'])
        response = _problem(ApiError(422, 'INPUT_XML_STRUCTURE_MISMATCH', 'Estrutura divergente.',
                                     xmlPath='Document/Record', reason='namespace-divergente'), 'trace')
        value = json.loads(response['body'])
        self.assertEqual(set(value), {'error', 'xmlPath', 'reason'})
        for name in value:
            self.assertIn(name, schema['properties'])
        for item in self.spec['components']['responses'].values():
            self.assertEqual(set(item['content']), {'application/json'})
        self.assertNotIn('Problem', self.spec['components']['schemas'])

    def test_openapi_examples_require_input_and_readme_documents_swagger(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('/swagger/', readme)
        self.assertIn('/openapi.json', readme)
        for operation in ('new', 'return'):
            post = self.spec['paths']['/api/v1/files/xml/{fileId}/' + operation]['post']
            examples = post['requestBody']['content']['application/json']['examples']
            for name, example in examples.items():
                with self.subTest(operation=operation, example=name):
                    payload = example['value']
                    validate_generation(operation, {**payload, 'fileId': 'file-1'})

