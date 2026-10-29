import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from mockaize_api import preset_codec as codec


FIXTURES = Path(__file__).parent / 'fixtures' / 'preset-v1'


class PresetCodecTests(unittest.TestCase):
    def test_shared_fixtures_match_payload_hash_and_exact_encoding(self):
        for name in ('minimal', 'complete'):
            with self.subTest(fixture=name):
                payload = json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))
                xml = (FIXTURES / f'{name}.mockaize.xml').read_bytes()
                expected_hash = (FIXTURES / f'{name}.sha256').read_text(encoding='ascii').strip()
                canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=False, allow_nan=False).encode('utf-8')
                self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected_hash)
                self.assertEqual(codec.decode_preset(xml), payload)
                self.assertEqual(codec.encode_preset(**payload), xml)

    def test_complete_fixture_covers_all_formula_types_and_untyped_type_note(self):
        payload = codec.decode_preset((FIXTURES / 'complete.mockaize.xml').read_bytes())
        root = ET.fromstring((FIXTURES / 'complete.mockaize.xml').read_bytes())
        formula_types = {element.tag.rsplit('}', 1)[-1] for element in root.iter()
                         if isinstance(element.tag, str) and element.tag.rsplit('}', 1)[-1] in codec.GENERATOR_TYPES}
        self.assertEqual(formula_types, codec.GENERATOR_TYPES)
        self.assertEqual(payload['configuration']['inputNotes']['types'][-1],
                         {'type': 'literal', 'value': 'ordinary object'})

    def test_invalid_hash_version_encoding_dtd_and_formula_position_fail_closed(self):
        xml = (FIXTURES / 'complete.mockaize.xml').read_bytes()
        invalid = [xml.replace(b'schemaVersion="1"', b'schemaVersion="2"', 1),
                   xml.replace(b'<cpf />', b'<notAFormula />', 1),
                   xml.replace(b'kind="boolean">true', b'kind="boolean">TRUE', 1),
                   xml.replace(b'<PayloadHash algorithm="sha256">', b'<PayloadHash algorithm="sha256">0', 1),
                   b'<!DOCTYPE x [<!ENTITY e "x">]>' + xml]
        for index, candidate in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(codec.PresetError):
                codec.decode_preset(candidate)
        utf16 = '<?xml version="1.0" encoding="UTF-16"?><x/>'.encode('utf-16')
        with self.assertRaises(codec.PresetError):
            codec.decode_preset(utf16)

    def test_invalid_timezone_and_reserved_id_are_rejected(self):
        payload = codec.decode_preset((FIXTURES / 'minimal.mockaize.xml').read_bytes())
        payload['context']['timeZone'] = 'Mars/Olympus'
        with self.assertRaises(codec.PresetError):
            codec.encode_preset(**payload)
        payload = codec.decode_preset((FIXTURES / 'minimal.mockaize.xml').read_bytes())
        payload['metadata']['id'] = 'CON'
        with self.assertRaises(codec.PresetError):
            codec.encode_preset(**payload)

    def test_formula_schema_and_structural_paths_are_validated(self):
        payload = codec.decode_preset((FIXTURES / 'minimal.mockaize.xml').read_bytes())
        payload['configuration']['rulesByMode'] = {
            'new': {'path': {'generator': {'type': 'literal', 'value': 'ok', 'unexpected': True}}}}
        with self.assertRaises(codec.PresetError):
            codec.encode_preset(**payload)
        payload['configuration']['rulesByMode']['new']['path']['generator'] = {
            'type': 'copy', 'path': 'not-json'}
        with self.assertRaises(codec.PresetError):
            codec.encode_preset(**payload)


if __name__ == '__main__':
    unittest.main()
