"""C-PRESET-1 typed XML codec used by the read-only API consumer."""
import hashlib
import hmac
import json
import math
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NAMESPACE = 'urn:mockaize:preset:1'
ET.register_namespace('', NAMESPACE)
ROOT_ATTRIBUTES = {'schemaVersion': '1', 'engineSpecVersion': '1', 'format': 'xml'}
GENERATOR_TYPES = {'literal', 'copy', 'field', 'groupSum', 'config', 'count', 'cpf', 'cnpj',
                   'list', 'hash', 'person', 'company', 'address', 'zeros', 'sequence',
                   'date', 'alpha', 'random', 'id', 'compose'}
FORMULA_FIELDS = {
    'groupSum': {'source', 'group', 'path', 'allRecords'},
    'literal': {'value'}, 'copy': {'path'}, 'field': {'source', 'path'},
    'config': set(), 'count': set(), 'cpf': {'mask'},
    'cnpj': {'mode', 'mask', 'establishment'}, 'list': {'values', 'mode', 'index'},
    'hash': {'length', 'format'}, 'person': {'field', 'group'},
    'company': {'field', 'group'}, 'address': {'field', 'state', 'group'},
    'zeros': {'length'}, 'sequence': {'start', 'step', 'width', 'scope'},
    'date': {'mode', 'days', 'format', 'value', 'holidays', 'custom'},
    'alpha': {'length', 'alphabet'}, 'random': {'min', 'max', 'decimals'},
    'id': {'mode', 'prefix', 'length'}, 'compose': {'operation', 'separator', 'parts'},
}


class PresetError(ValueError):
    """Invalid, unsafe, or unsupported C-PRESET-1 payload."""


def _tag(name):
    return f'{{{NAMESPACE}}}{name}'


def _formula_position(path):
    if path and path[-1] == 'filename':
        return (path[:-1] in (('filter',), ('manual',)) or
                len(path) == 4 and path[0] == 'filterPresets' and isinstance(path[1], int) and path[2] == 'filter' or
                len(path) == 3 and path[0] == 'returnModels' and isinstance(path[1], int))
    if len(path) == 2 and path[0] == 'filenameByMode':
        return path[1] in ('new', 'return')
    if len(path) == 3 and path[:2] == ('manual', 'formulas'):
        return True
    if len(path) == 4 and path[0] == 'rulesByMode' and path[1] in ('new', 'return') and path[-1] == 'generator':
        return True
    if len(path) == 5 and path[0] == 'returnModels' and isinstance(path[1], int) and path[2] == 'rules' and path[-1] == 'generator':
        return True
    return False


def _json_value(value):
    if type(value) is str:
        if any(not (c in '\t\n\r' or '\x20' <= c <= '\ud7ff' or '\ue000' <= c <= '\ufffd' or '\U00010000' <= c <= '\U0010ffff') for c in value):
            raise PresetError('Preset text contains characters forbidden by XML 1.0.')
    elif value is None or type(value) in (bool, int):
        return
    elif type(value) is float and math.isfinite(value):
        return
    elif type(value) is list:
        for item in value:
            _json_value(item)
    elif type(value) is dict and all(type(key) is str for key in value):
        for key, item in value.items():
            _json_value(key)
            _json_value(item)
    else:
        raise PresetError('Preset values must be finite JSON values.')


def canonical_payload(metadata, configuration, context):
    payload = {'metadata': metadata, 'configuration': configuration, 'context': context}
    _json_value(payload)
    try:
        return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    except (ValueError, UnicodeError) as exc:
        raise PresetError('Invalid JSON text in preset.') from exc


def payload_hash(metadata, configuration, context):
    return hashlib.sha256(canonical_payload(metadata, configuration, context)).hexdigest()


def _validate(metadata, configuration, context):
    _json_value({'metadata': metadata, 'configuration': configuration, 'context': context})
    if type(metadata) is not dict or set(metadata) != {'id', 'name', 'libraryPath', 'revision', 'fileIndex', 'active'}:
        raise PresetError('Invalid preset metadata fields.')
    if any(type(metadata[key]) is not str for key in ('id', 'name', 'libraryPath')) or not metadata['id']:
        raise PresetError('Invalid preset metadata text.')
    if (not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', metadata['id']) or
            re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', metadata['id'], re.I)):
        raise PresetError('Invalid preset ID.')
    if any(type(metadata[key]) is not int or metadata[key] < (1 if key == 'revision' else 0)
           for key in ('revision', 'fileIndex')) or type(metadata['active']) is not bool:
        raise PresetError('Invalid preset metadata types.')
    if type(context) is not dict or set(context) != {'timeZone'} or type(context['timeZone']) is not str or not context['timeZone']:
        raise PresetError('Invalid preset context.')
    try:
        ZoneInfo(context['timeZone'])
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise PresetError('Invalid preset time zone.') from exc
    if type(configuration) is not dict:
        raise PresetError('Preset configuration must be an object.')


def _validate_path(value):
    if not isinstance(value, str) or len(value) > 16_384:
        raise ValueError('Invalid structural path.')
    parts = json.loads(value)
    if not isinstance(parts, list) or not parts or len(parts) > 128:
        raise ValueError('Invalid structural path.')
    for index, part in enumerate(parts):
        if not isinstance(part, dict) or set(part) - {'ns', 'name', 'index', 'attribute'}:
            raise ValueError('Invalid structural path segment.')
        if not isinstance(part.get('ns', ''), str) or not isinstance(part.get('name'), str) or not part['name']:
            raise ValueError('Invalid structural path segment.')
        attribute = part.get('attribute', False)
        if type(attribute) is not bool or attribute and index != len(parts) - 1:
            raise ValueError('Invalid structural path attribute.')
        if attribute:
            if 'index' in part:
                raise ValueError('Attribute path cannot have an index.')
        elif type(part.get('index')) is not int or part['index'] < 1:
            raise ValueError('Invalid structural path index.')


def _validate_formula(formula, depth=0):
    if (not isinstance(formula, dict) or not isinstance(formula.get('type'), str) or
            formula['type'] not in GENERATOR_TYPES or depth > 6):
        raise ValueError('Invalid typed formula or excessive composition depth.')
    kind = formula['type']
    if set(formula) - ({'type'} | FORMULA_FIELDS[kind]):
        raise ValueError('Formula has unknown properties.')
    if kind == 'date' and 'custom' in formula:
        custom = formula['custom']
        flags = {'day', 'month', 'year', 'hour', 'minute', 'second', 'milliseconds', 'timezone'}
        choices = {'order': {'DMY', 'YMD', 'MDY'}, 'yearDigits': {'2', '4'},
                   'dateSeparator': {'', '/', '-', '.'}, 'timeSeparator': {'', ':', '.'},
                   'join': {'', ' ', 'T'}, 'zone': {'app', 'utc'}}
        if not isinstance(custom, dict) or set(custom) - (flags | set(choices)):
            raise ValueError('Invalid custom date format.')
        if any(type(custom[key]) is not bool for key in flags & set(custom)):
            raise ValueError('Date components must be booleans.')
        if any(not isinstance(custom[key], str) or custom[key] not in values
               for key, values in choices.items() if key in custom):
            raise ValueError('Invalid custom date choice.')
        if (formula.get('format') == 'custom' and
                not any(custom.get(key, True) for key in ('day', 'month', 'year', 'hour', 'minute', 'second'))):
            raise ValueError('Custom date needs at least one visible component.')
    if kind in {'copy', 'field', 'groupSum'}:
        _validate_path(formula.get('path'))
    if kind in {'field', 'groupSum'} and formula.get('source', 'output') not in {'input', 'output'}:
        raise ValueError('Invalid field source.')
    if kind == 'groupSum':
        if 'allRecords' in formula and type(formula['allRecords']) is not bool:
            raise ValueError('allRecords must be boolean.')
        _validate_path(formula.get('group'))
        group, field = json.loads(formula['group']), json.loads(formula['path'])
        if (group[-1].get('attribute') or len(field) <= len(group) or
                any(part.get('name') != field[i].get('name') or part.get('ns') != field[i].get('ns') or
                    i < len(group) - 1 and part.get('index') != field[i].get('index')
                    for i, part in enumerate(group))):
            raise ValueError('Summed field must be inside its group.')
    if kind == 'compose':
        parts = formula.get('parts')
        if not isinstance(parts, list) or not 1 <= len(parts) <= 100:
            raise ValueError('Compose needs between one and one hundred parts.')
        if formula.get('operation', 'concat') not in {'concat', 'sum'}:
            raise ValueError('Invalid compose operation.')
        for child in parts:
            _validate_formula(child, depth + 1)


def _encode(value, path=(), configuration=False, formula=False):
    element = ET.Element(_tag('Value'))
    is_formula = formula or configuration and _formula_position(path) and isinstance(value, dict) and bool(value)
    if is_formula:
        try:
            _validate_formula(value)
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            raise PresetError('Invalid formula.') from exc
        element.set('kind', 'formula')
        body = ET.SubElement(element, _tag(value['type']))
        for key in sorted(set(value) - {'type'}):
            prop = ET.SubElement(body, _tag('Property'), {'name': key})
            child = value[key]
            if value['type'] == 'compose' and key == 'parts':
                if type(child) is not list:
                    raise PresetError('Compose parts must be an array.')
                array = ET.SubElement(prop, _tag('Value'), {'kind': 'array'})
                for part in child:
                    ET.SubElement(array, _tag('Item')).append(_encode(part, formula=True))
            else:
                prop.append(_encode(child))
    elif type(value) is dict:
        element.set('kind', 'object')
        for key in sorted(value):
            ET.SubElement(element, _tag('Property'), {'name': key}).append(
                _encode(value[key], path + (key,), configuration))
    elif type(value) is list:
        element.set('kind', 'array')
        for index, item in enumerate(value):
            ET.SubElement(element, _tag('Item')).append(_encode(item, path + (index,), configuration))
    elif type(value) is str:
        element.set('kind', 'string')
        element.text = value
    elif type(value) is bool:
        element.set('kind', 'boolean')
        element.text = 'true' if value else 'false'
    elif value is None:
        element.set('kind', 'null')
    else:
        element.set('kind', 'number')
        element.text = json.dumps(value, allow_nan=False)
    return element


def encode_preset(metadata, configuration, context):
    """Encode a Site-produced snapshot; kept for exact fixture round-trip tests."""
    _validate(metadata, configuration, context)
    root = ET.Element(_tag('MockAiZePreset'), ROOT_ATTRIBUTES)
    for name, value in (('Metadata', metadata), ('Configuration', configuration), ('Context', context)):
        ET.SubElement(root, _tag(name)).append(_encode(value, configuration=name == 'Configuration'))
    ET.SubElement(root, _tag('PayloadHash'), {'algorithm': 'sha256'}).text = payload_hash(metadata, configuration, context)
    ET.indent(root, space='  ')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True).replace(b'\r', b'&#13;') + b'\n'


def _structure(element, name, attrs, children=None, text=False):
    if element.tag != _tag(name) or element.attrib != attrs:
        raise PresetError(f'Invalid {name} element or attributes.')
    if not text and (element.text or '').strip():
        raise PresetError(f'Unexpected text in {name}.')
    if children is not None and len(element) != children:
        raise PresetError(f'Invalid child count in {name}.')
    if any((child.tail or '').strip() for child in element):
        raise PresetError(f'Unexpected tail text in {name}.')


def _decode(element, path=(), configuration=False, formula=False):
    kind = element.get('kind')
    _structure(element, 'Value', {'kind': kind}, text=kind in ('string', 'boolean', 'number'))
    semantic_formula = formula or configuration and _formula_position(path)
    if kind == 'formula':
        if not semantic_formula or len(element) != 1:
            raise PresetError('Formula outside a semantic formula position.')
        body = element[0]
        name = body.tag.removeprefix(f'{{{NAMESPACE}}}') if isinstance(body.tag, str) else ''
        if name not in GENERATOR_TYPES:
            raise PresetError('Unknown formula type.')
        _structure(body, name, {})
        result = {'type': name}
        for prop in body:
            key = prop.get('name')
            _structure(prop, 'Property', {'name': key}, 1)
            if key is None or key in result:
                raise PresetError('Duplicate or unnamed formula property.')
            if name == 'compose' and key == 'parts':
                array = prop[0]
                _structure(array, 'Value', {'kind': 'array'})
                result[key] = []
                for item in array:
                    _structure(item, 'Item', {}, 1)
                    result[key].append(_decode(item[0], formula=True))
            else:
                result[key] = _decode(prop[0])
        try:
            _validate_formula(result)
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            raise PresetError('Invalid formula.') from exc
        return result
    if kind == 'object':
        result = {}
        for prop in element:
            key = prop.get('name')
            _structure(prop, 'Property', {'name': key}, 1)
            if key is None or key in result:
                raise PresetError('Duplicate or unnamed object property.')
            result[key] = _decode(prop[0], path + (key,), configuration)
        if semantic_formula and result:
            raise PresetError('Formula must use kind=formula.')
        return result
    if kind == 'array':
        result = []
        for index, item in enumerate(element):
            _structure(item, 'Item', {}, 1)
            result.append(_decode(item[0], path + (index,), configuration))
        return result
    if len(element):
        raise PresetError('Scalar Value cannot contain elements.')
    value = element.text or ''
    if kind == 'string':
        return value
    if kind == 'null' and value == '':
        return None
    if kind == 'boolean' and value in ('true', 'false'):
        return value == 'true'
    if kind == 'number' and re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?', value):
        result = json.loads(value)
        if type(result) is int or math.isfinite(result):
            return result
    raise PresetError('Unknown kind or invalid scalar value.')


def decode_preset(xml):
    """Validate a C-PRESET-1 document and return its logical payload."""
    try:
        text = xml.decode('utf-8-sig') if isinstance(xml, bytes) else xml
        if not isinstance(text, str) or re.search(r'<!\s*(?:DOCTYPE|ENTITY)', text, re.I) or '\x00' in text:
            raise PresetError('DOCTYPE, entities and non-UTF-8 presets are forbidden.')
        declaration = re.match(r"\s*<\?xml\s+[^?]*encoding=['\"]([^'\"]+)", text, re.I)
        if declaration and declaration[1].lower() not in ('utf-8', 'utf8'):
            raise PresetError('Preset encoding must be UTF-8.')
        root = ET.fromstring(text, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
        _structure(root, 'MockAiZePreset', ROOT_ATTRIBUTES, 4)
        payload = {}
        for name, child in zip(('Metadata', 'Configuration', 'Context'), root[:3]):
            _structure(child, name, {}, 1)
            payload[name.lower()] = _decode(child[0], configuration=name == 'Configuration')
        _structure(root[3], 'PayloadHash', {'algorithm': 'sha256'}, 0, text=True)
        digest = root[3].text or ''
        _validate(payload['metadata'], payload['configuration'], payload['context'])
        if not re.fullmatch(r'[0-9a-f]{64}', digest) or not hmac.compare_digest(digest, payload_hash(**payload)):
            raise PresetError('Preset payload hash mismatch.')
        return payload
    except PresetError:
        raise
    except (ET.ParseError, UnicodeError, ValueError, TypeError, RecursionError, AttributeError) as exc:
        raise PresetError('Invalid preset XML.') from exc
