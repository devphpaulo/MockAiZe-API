import unittest
from mockaize_api.formulas import evaluate
from mockaize_api.preset_codec import _validate_formula

class FakerIntegrationTests(unittest.TestCase):
    def test_person_profile_shared_with_email_and_legacy(self):
        context = {}
        name = evaluate({'type':'faker','catalogVersion':1,'catalogId':'person.name'}, context)
        first = evaluate({'type':'person','field':'firstName'}, context)
        email = evaluate({'type':'faker','catalogVersion':1,'catalogId':'internet.email'}, context)
        self.assertTrue(name.startswith(first + ' '))
        self.assertTrue(email.endswith('@example.test'))

    def test_formula_validation_rejects_unknown_and_duplicate_components(self):
        for formula in ({'type':'faker','catalogVersion':1,'catalogId':'person.unknown'},
                        {'type':'faker','catalogVersion':1,'catalogId':'person.name','params':{'components':['first_name','first_name']}}):
            with self.assertRaises(ValueError): _validate_formula(formula)

    def test_valid_faker_formula(self):
        _validate_formula({'type':'faker','catalogVersion':1,'catalogId':'person.name'})

class FakerEngineTests(unittest.TestCase):
    def test_new_shares_profile_with_filename_per_first_record(self):
        import json
        from xml.etree import ElementTree
        from mockaize_api.xml_engine import generate_new
        def path(*names):
            return json.dumps([{'ns':'','name':name,'index':1} for name in names])
        name = {'type':'faker','catalogVersion':1,'catalogId':'person.first_name'}
        variation = {'name':'test','config':{'inputByMode':{'new':{'xml':'<root><r><a/></r></root>','group':path('root','r')}},
                    'rulesByMode':{'new':{path('root','r','a'):{'generator':name}}},
                    'filenameByMode':{'new':name}}}
        result = generate_new(variation, 2)[0]
        values = [item.text for item in ElementTree.fromstring(result['content']).findall('./r/a')]
        self.assertEqual(result['fileName'], values[0] + '.xml')

    def test_faker_preset_round_trip_and_hash_validation(self):
        import json
        from pathlib import Path
        from mockaize_api import preset_codec as codec
        payload = json.loads((Path(__file__).parent / 'fixtures/preset-v1/minimal.json').read_text(encoding='utf-8'))
        payload['configuration']['filenameByMode'] = {'new':{'type':'faker','catalogVersion':1,'catalogId':'person.first_name'}}
        xml = codec.encode_preset(**payload)
        self.assertEqual(codec.decode_preset(xml), payload)
        with self.assertRaises(codec.PresetError):
            codec.decode_preset(xml.replace(b'person.first_name', b'person.last_name'))

    def test_address_profile_state_and_components(self):
        context = {}
        base = {'type':'faker','catalogVersion':1,'params':{'state':'CE'}}
        state = evaluate({**base,'catalogId':'address.state_abbr'}, context)
        city = evaluate({**base,'catalogId':'address.city'}, context)
        combined = evaluate({**base,'catalogId':'address.address','params':{'state':'CE','components':['city','state_abbr']}}, context)
        self.assertEqual((state, city, combined), ('CE', 'Fortaleza', 'Fortaleza, CE'))

    def test_company_cnpj_parameters(self):
        from mockaize_api.formulas import valid_cnpj
        value = evaluate({'type':'faker','catalogVersion':1,'catalogId':'company.company_id',
                          'params':{'mode':'A','mask':'yes','establishment':'0001'}}, {})
        self.assertTrue(valid_cnpj(value))
        self.assertEqual(value.split('/')[1][:4], '0001')

    def test_site_authored_fixture_is_accepted(self):
        from pathlib import Path
        from mockaize_api.preset_codec import decode_preset
        payload = decode_preset((Path(__file__).parent / 'fixtures/faker-site-v1.xml').read_bytes())
        self.assertEqual(payload['configuration']['manual']['fakerSeed'], 'fixture-seed')
        self.assertEqual(payload['configuration']['filenameByMode']['new']['catalogId'], 'person.first_name')
