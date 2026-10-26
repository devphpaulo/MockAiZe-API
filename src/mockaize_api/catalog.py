"""Read-only adapter for the independently versioned Studio SQLite format."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET

from .errors import ApiError


_REQUIRED_COLUMNS = {
    'app_meta': {'key', 'value'}, 'schema_meta': {'key', 'value'},
    'library_nodes': {'id', 'parent_id', 'kind', 'name', 'deleted_at'},
    'variations': {'id', 'config_json', 'file_index', 'revision'},
}


def _unavailable():
    return ApiError(503, 'DEPENDENCY_UNAVAILABLE',
                    'O catálogo está indisponível ou usa um formato não suportado.')


def _invalid_cursor():
    return ApiError(400, 'INVALID_REQUEST', 'Paginação ou filtro inválido.')


def _template_ready(xml, group):
    """Resolve the Studio JSON path, including namespaces and sibling indexes."""
    if not isinstance(xml, str) or not isinstance(group, str):
        return False
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)', xml, re.I):
        return False
    try:
        root, parts = ET.fromstring(xml), json.loads(group)
        if not isinstance(parts, list) or not parts:
            return False
        candidates = [root]
        node = None
        for part in parts:
            if not isinstance(part, dict) or part.get('attribute'):
                return False
            name, namespace, index = part.get('name'), part.get('ns', ''), part.get('index', 1)
            if not isinstance(name, str) or not isinstance(namespace, str):
                return False
            if type(index) is not int or index < 1:
                return False
            tag = '{' + namespace + '}' + name if namespace else name
            matches = [element for element in candidates if element.tag == tag]
            if len(matches) < index:
                return False
            node = matches[index - 1]
            candidates = list(node)
        return node is not None and bool(len(node))
    except (ValueError, TypeError, ET.ParseError, RecursionError):
        return False


def _input_ready(config, mode):
    inputs = config.get('inputByMode', {})
    document = inputs.get(mode, {}) if isinstance(inputs, dict) else {}
    return isinstance(document, dict) and _template_ready(document.get('xml'), document.get('group'))


def _models(config):
    models = config.get('returnModels', [])
    if not isinstance(models, list) or len(models) > 20:
        raise _unavailable()
    identities = set()
    for model in models:
        if not isinstance(model, dict):
            raise _unavailable()
        identity, name = model.get('id'), model.get('name')
        if not isinstance(identity, str) or not identity or identity in identities or not isinstance(name, str):
            raise _unavailable()
        identities.add(identity)
    return models


def _return_items(config):
    input_ready = _input_ready(config, 'return')
    return [{'id': model['id'], 'name': model['name'],
             'ready': input_ready and _template_ready(model.get('outputXml'), model.get('outputGroup'))}
            for model in _models(config)]


class Catalog:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    @contextmanager
    def _read(self):
        connection = None
        try:
            uri = self.database_path.resolve().as_uri() + '?mode=ro'
            connection = sqlite3.connect(uri, uri=True, timeout=2)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            self._validate_schema(connection)
            yield connection
        except (sqlite3.Error, OSError, ValueError, TypeError, RecursionError) as error:
            raise _unavailable() from error
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _validate_schema(connection):
        for table, required in _REQUIRED_COLUMNS.items():
            columns = {row['name'] for row in connection.execute(f'PRAGMA table_info({table})')}
            if not required <= columns:
                raise _unavailable()
        for table, key in [('app_meta', 'schema_version'), ('schema_meta', 'version')]:
            row = connection.execute(f'SELECT value FROM {table} WHERE key=?', (key,)).fetchone()
            if row is None or row['value'] != '2':
                raise _unavailable()

    def check(self):
        with self._read():
            pass

    @staticmethod
    def _visible_nodes(connection):
        nodes = {row['id']: dict(row) for row in connection.execute('SELECT * FROM library_nodes')}
        visible = {}
        for identity, node in nodes.items():
            path, visited, current = [], set(), node
            while current is not None:
                if current['deleted_at'] is not None or current['id'] in visited:
                    break
                visited.add(current['id'])
                path.append(current['name'])
                parent_id = current['parent_id']
                if parent_id is None:
                    visible[identity] = (node, ' / '.join(reversed(path)))
                    break
                current = nodes.get(parent_id)
        return visible

    def snapshot(self, file_id: str):
        if not isinstance(file_id, str) or not file_id or len(file_id) > 128:
            raise ApiError(400, 'INVALID_REQUEST', 'Identificador de arquivo inválido.')
        with self._read() as connection:
            visible = self._visible_nodes(connection)
            node_path = visible.get(file_id)
            if node_path is None or node_path[0]['kind'] != 'variation':
                raise ApiError(404, 'FILE_NOT_FOUND', 'Arquivo não encontrado.')
            row = connection.execute('SELECT id,revision,file_index,config_json FROM variations WHERE id=?', (file_id,)).fetchone()
            if row is None:
                raise _unavailable()
            if type(row['revision']) is not int or row['revision'] < 1 or type(row['file_index']) is not int or row['file_index'] < 0:
                raise _unavailable()
            config = json.loads(row['config_json'])
            if not isinstance(config, dict):
                raise _unavailable()
            _models(config)
            return {'id': row['id'], 'name': node_path[0]['name'],
                    'revision': row['revision'], 'file_index': row['file_index'],
                    'config': config, 'libraryPath': node_path[1]}

    def file(self, file_id: str):
        snapshot = self.snapshot(file_id)
        return {key: snapshot[key] for key in ('id', 'name', 'libraryPath', 'revision')}

    def files(self, q: str = '', limit: int = 100, cursor: str | None = None):
        if not isinstance(q, str) or len(q) > 512 or type(limit) is not int or not 1 <= limit <= 200:
            raise _invalid_cursor()
        query = q.casefold()
        after = self._decode_cursor(cursor, query) if cursor is not None else None
        with self._read() as connection:
            visible = self._visible_nodes(connection)
            items = []
            for row in connection.execute('SELECT id,revision FROM variations'):
                node_path = visible.get(row['id'])
                if node_path is None or node_path[0]['kind'] != 'variation':
                    continue
                name = node_path[0]['name']
                key = (name.casefold(), row['id'])
                if query in name.casefold() and (after is None or key > after):
                    items.append({'id': row['id'], 'name': name, 'libraryPath': node_path[1], 'revision': row['revision']})
        items.sort(key=lambda item: (item['name'].casefold(), item['id']))
        page = items[:limit]
        next_cursor = None
        if len(items) > limit:
            last = page[-1]
            payload = [1, hashlib.sha256(query.encode()).hexdigest(), last['name'].casefold(), last['id']]
            next_cursor = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode().rstrip('=')
        return {'items': page, 'nextCursor': next_cursor}

    @staticmethod
    def _decode_cursor(cursor, query):
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096:
            raise _invalid_cursor()
        try:
            raw = base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True)
            payload = json.loads(raw)
            if (not isinstance(payload, list) or len(payload) != 4 or payload[0] != 1
                    or payload[1] != hashlib.sha256(query.encode()).hexdigest()
                    or not all(isinstance(part, str) for part in payload[2:])):
                raise _invalid_cursor()
            return tuple(payload[2:])
        except (ValueError, UnicodeError) as error:
            raise _invalid_cursor() from error

    def modes(self, file_id: str):
        snapshot = self.snapshot(file_id)
        config = snapshot['config']
        new_missing = [] if _input_ready(config, 'new') else ['NEW_INPUT_TEMPLATE_NOT_READY']
        return_missing = [] if _input_ready(config, 'return') else ['RETURN_INPUT_TEMPLATE_NOT_READY']
        if not any(item['ready'] for item in _return_items(config)):
            return_missing.append('RETURN_NOT_READY')
        items = [{'id': 'new', 'name': 'Novos registros', 'ready': not new_missing, 'missingRequirements': new_missing},
                 {'id': 'return', 'name': 'Retorno', 'ready': not return_missing, 'missingRequirements': return_missing}]
        return {'fileId': snapshot['id'], 'fileName': snapshot['name'], 'items': items}

    def returns(self, file_id: str):
        snapshot = self.snapshot(file_id)
        return {'fileId': snapshot['id'], 'fileName': snapshot['name'], 'items': _return_items(snapshot['config'])}
