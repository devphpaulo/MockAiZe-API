from http.client import HTTPConnection
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import socket
import time
import unittest
from unittest.mock import patch

from fixtures.catalog_factory import create_catalog
from mockaize_api.config import ApiConfig, save_config
from mockaize_api.errors import ApiError
from mockaize_api.runtime import ApiServer, Application, _problem
from mockaize_api.security import create_credentials


class HttpTests(unittest.TestCase):
    source_xml = '<Document><Record><Value>example</Value></Record></Document>'

    def test_error_before_body_read_delivers_json_with_unread_windows_socket_bytes(self):
        from http.client import HTTPResponse
        reached, release = threading.Event(), threading.Event()
        actual = self.server.application.log.write
        def pause(**values):
            if values.get('method') == 'POST' and values.get('route') == '/openapi.json':
                reached.set()
                release.wait(2)
            return actual(**values)
        client = socket.create_connection(self.server.server_address, timeout=3)
        try:
            with patch.object(self.server.application.log, 'write', side_effect=pause):
                client.sendall(b'POST /openapi.json HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: 1024\r\n\r\n')
                self.assertTrue(reached.wait(2))
                client.sendall(b'x' * 1024)
                release.set()
                response = HTTPResponse(client)
                response.begin()
                self.assertEqual(response.status, 405)
                self.assertEqual(json.loads(response.read())['error']['code'], 'METHOD_NOT_ALLOWED')
        finally:
            release.set()
            client.close()

    def test_directory_replay_missing_or_replaced_is_410_without_generation_or_state_change(self):
        route = '/api/v1/files/xml/file-1/new'
        payload = {'recordCount': 1, 'delivery': 'directory'}
        for change in ('missing', 'same-size-replacement', 'different-size'):
            headers = {'Idempotency-Key': 'artifact-' + change}
            status, _, body = self.call('POST', route, payload, headers)
            self.assertEqual(status, 200, body)
            value = json.loads(body)
            path = self.root / 'output' / value['files'][0]['fileName']
            with self.server.application.state.connect() as connection:
                before = connection.execute('SELECT next_index FROM sequences WHERE file_id=?', ('file-1',)).fetchone()
                replay = connection.execute('SELECT status,headers,body FROM replays WHERE key=?',
                                            (headers['Idempotency-Key'],)).fetchone()
            if change == 'missing':
                path.unlink()
            elif change == 'same-size-replacement':
                path.write_bytes(path.read_bytes().replace(b'example', b'changed'))
            else:
                path.write_bytes(b'replaced')
            with patch('mockaize_api.runtime.run_engine') as engine:
                status, response_headers, content = self.call('POST', route, payload, headers)
            engine.assert_not_called()
            result = json.loads(content)
            self.assertEqual((status, result['error']['code']), (410, 'OUTPUT_EXPIRED'))
            self.assertEqual(result['error']['traceId'], response_headers['X-Request-ID'])
            self.assertNotEqual(result['error']['traceId'], value['requestId'])
            self.assertNotIn('X-Idempotent-Replay', response_headers)
            with self.server.application.state.connect() as connection:
                self.assertEqual(connection.execute('SELECT next_index FROM sequences WHERE file_id=?',
                                                    ('file-1',)).fetchone(), before)
                self.assertEqual(connection.execute('SELECT status,headers,body FROM replays WHERE key=?',
                                                    (headers['Idempotency-Key'],)).fetchone(), replay)

    def test_directory_replay_permission_failure_is_503_and_preserves_replay(self):
        route = '/api/v1/files/xml/file-1/new'
        payload = {'recordCount': 1}
        headers = {'Idempotency-Key': 'artifact-inaccessible'}
        status, _, body = self.call('POST', route, payload, headers)
        self.assertEqual(status, 200, body)
        path = self.root / 'output' / json.loads(body)['files'][0]['fileName']
        actual = Path.open
        def denied(candidate, *args, **kwargs):
            if candidate == path:
                raise PermissionError
            return actual(candidate, *args, **kwargs)
        with patch('pathlib.Path.open', new=denied), patch('mockaize_api.runtime.run_engine') as engine:
            status, _, content = self.call('POST', route, payload, headers)
        engine.assert_not_called()
        self.assertEqual((status, json.loads(content)['error']['code']), (503, 'DEPENDENCY_UNAVAILABLE'))
        status, replay_headers, replay = self.call('POST', route, payload, headers)
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay, body)
        self.assertEqual(replay_headers['X-Idempotent-Replay'], 'true')

    def test_content_and_inline_replay_survive_missing_output_directory(self):
        route = '/api/v1/files/xml/file-1/new'
        for delivery in ('content', 'inline'):
            payload = {'recordCount': 1, 'delivery': delivery}
            headers = {'Idempotency-Key': 'persistent-' + delivery}
            status, _, body = self.call('POST', route, payload, headers)
            self.assertEqual(status, 200, body)
            (self.root / 'output').rmdir()
            try:
                status, replay_headers, replay = self.call('POST', route, payload, headers)
                self.assertEqual(status, 200, replay)
                self.assertEqual(replay, body)
                self.assertEqual(replay_headers['X-Idempotent-Replay'], 'true')
            finally:
                (self.root / 'output').mkdir()

    def test_serve_starts_one_cleanup_round_and_answers_while_scan_is_blocked(self):
        from mockaize_api.housekeeping import Housekeeping
        from mockaize_api.runtime import serve
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        values = self.server.application.config.to_mapping()
        values['port'] = port
        save_config(self.config_path, ApiConfig.from_mapping(values))
        reached, release, stop = threading.Event(), threading.Event(), threading.Event()
        cleaners = []
        def factory(*args, **kwargs):
            cleaner = Housekeeping(*args, **kwargs)
            cleaners.append(cleaner)
            return cleaner
        def blocked_scan(*args):
            reached.set()
            release.wait(3)
            return False
        with patch('mockaize_api.runtime.Housekeeping', side_effect=factory), \
                patch.object(Housekeeping, '_scan_root', side_effect=blocked_scan):
            thread = threading.Thread(target=serve, args=(self.config_path, stop))
            thread.start()
            try:
                self.assertTrue(reached.wait(2))
                connection = HTTPConnection('127.0.0.1', port, timeout=2)
                try:
                    connection.request('GET', '/health')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200, response.read())
                finally:
                    connection.close()
                self.assertEqual(len(cleaners), 1)
                self.assertFalse(cleaners[0].start())
            finally:
                stop.set()
                release.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertTrue(cleaners[0].finished.is_set())

    def configure_limits(self, limits):
        values = self.server.application.config.to_mapping()
        values['limits'] = limits
        save_config(self.config_path, ApiConfig.from_mapping(values))
        self.server.application = Application(self.config_path)

    def test_return_requires_nonempty_input_and_rejects_file_origin(self):
        route = '/api/v1/files/xml/file-1/return'
        base = {'returnSelection': {'type': 'all'}, 'delivery': 'content'}
        cases = [base, *[dict(base, inputXml=value) for value in ('', '  ', None, 1, True)],
                 dict(base, inputFilePath='ignored.xml'),
                 dict(base, inputXml=self.source_xml, inputFilePath='ignored.xml')]
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.call('POST', route, payload)[0], 400)

    def test_custom_and_disabled_records_reach_engine_and_first_checks_total_source(self):
        source = '<Document>' + '<Record><Value>one</Value></Record>' * 1000 + '</Document>'
        route = '/api/v1/files/xml/file-1/return'
        payload = {'returnSelection': {'type': 'all'}, 'inputXml': source,
                   'inputRecords': 'first', 'delivery': 'content'}
        status, _, body = self.call('POST', route, payload)
        self.assertEqual((status, json.loads(body)['error']['code']), (422, 'RECORD_LIMIT_EXCEEDED'))
        for rule in ({'mode': 'custom', 'count': 1000}, {'mode': 'disabled'}):
            self.configure_limits({'records': rule})
            with self.subTest(rule=rule):
                status, _, body = self.call('POST', '/api/v1/files/xml/file-1/new',
                                            {'recordCount': 1000, 'delivery': 'content'})
                self.assertEqual(status, 200, body)
                self.assertEqual(json.loads(body)['files'][0]['records'], 1000)
                status, _, body = self.call('POST', route, dict(payload, inputRecords='all', composition='mixed'))
                self.assertEqual(status, 200, body)
                self.assertEqual(json.loads(body)['totalRecords'], 2000)
                if rule['mode'] == 'custom':
                    self.assertEqual(self.call('POST', '/api/v1/files/xml/file-1/new',
                                              {'recordCount': 1001})[0], 400)
                    above = source.replace('</Document>', '<Record><Value>extra</Value></Record></Document>')
                    status, _, body = self.call('POST', route, dict(payload, inputXml=above))
                    self.assertEqual((status, json.loads(body)['error']['code']), (422, 'RECORD_LIMIT_EXCEEDED'))

    def test_input_limit_checks_decoded_utf8_with_escaped_body_above_old_12mib_cap(self):
        source = '<Document><Record><Value>' + '😀' * 1100000 + '</Value></Record></Document>'
        payload = {'returnSelection': {'type': 'all'}, 'inputXml': source, 'delivery': 'content'}
        self.assertGreater(len(json.dumps(payload).encode()), 12 * 1024 * 1024)
        size = len(source.encode('utf-8'))
        route = '/api/v1/files/xml/file-1/return'
        self.configure_limits({'inputXml': {'mode': 'custom', 'bytes': size - 1}})
        self.assertEqual(self.call('POST', route, payload)[0], 413)
        for rule in ({'mode': 'custom', 'bytes': size}, {'mode': 'disabled'}):
            self.configure_limits({'inputXml': rule})
            with self.subTest(rule=rule):
                status, _, body = self.call('POST', route, payload)
                self.assertEqual(status, 200, body)
                self.assertEqual(len(json.loads(body)['files']), 2)

    def test_all_deliveries_have_no_legacy_output_byte_cap(self):
        document = {'fileName': 'uncapped.xml', 'records': 1, 'content': b'<Document/>'}
        actual_len = len
        def measured_size(value):
            return 100000001 if isinstance(value, bytes) else actual_len(value)
        with patch('mockaize_api.runtime.len', side_effect=measured_size, create=True), \
                patch('mockaize_api.runtime.run_engine', return_value=[document]):
            for delivery in ('directory', 'content', 'inline'):
                with self.subTest(delivery=delivery):
                    response = self.server.application.generate('new',
                        {'fileId': 'file-1', 'recordCount': 1, 'delivery': delivery}, 'uncapped-test', None)
                    self.assertEqual(response['status'], 200, response['body'])

    def test_catalog_readiness_has_no_http_input_cap_on_saved_models(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.root / 'source.sqlite3')) as database, database:
            config = json.loads(database.execute('SELECT config_json FROM variations').fetchone()[0])
            large = '<Document><Record><Value>' + 'x' * 2000000 + '</Value></Record></Document>'
            config['inputByMode']['new']['xml'] = large
            config['returnModels'][0]['outputXml'] = large
            database.execute('UPDATE variations SET config_json=?', (json.dumps(config),))
        status, _, body = self.call('GET', '/api/v1/files/xml/file-1/modes')
        self.assertEqual(status, 200, body)
        self.assertTrue(all(item['ready'] for item in json.loads(body)['items']))
        status, _, body = self.call('GET', '/api/v1/files/xml/file-1/returns')
        self.assertEqual(status, 200, body)
        self.assertTrue(all(item['ready'] for item in json.loads(body)['items']))

    def test_invalid_unicode_input_is_a_sanitized_xml_error_with_disabled_limit(self):
        for rule in ({'mode': 'default'}, {'mode': 'disabled'}):
            self.configure_limits({'inputXml': rule})
            status, _, body = self.call('POST', '/api/v1/files/xml/file-1/return',
                {'returnSelection': {'type': 'all'}, 'inputXml': '<Document>\ud800</Document>'})
            self.assertEqual((status, json.loads(body)['error']['code']), (422, 'INPUT_XML_INVALID'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ['input', 'output', 'logs']:
            (self.root / folder).mkdir()
        database = self.root / 'source.sqlite3'
        create_catalog(database)
        self.config_path = self.root / 'config.json'
        save_config(self.config_path, ApiConfig(database, self.root / 'input', self.root / 'output',
                                              self.root / 'logs', 6578, '127.0.0.1', 'N'))
        (self.root / 'policy.json').write_text(json.dumps({'requests_per_second': 100}))
        self.key = create_credentials(self.config_path)
        self.server = ApiServer(('127.0.0.1', 0), Application(self.config_path))
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()

    def call(self, method, route, value=None, headers=None, authenticated=True):
        merged = {'X-API-Key': self.key} if authenticated else {}
        if value is not None:
            merged['Content-Type'] = 'application/json'
        merged.update(headers or {})
        body = json.dumps(value).encode() if value is not None else None
        connection = HTTPConnection(*self.server.server_address, timeout=15)
        try:
            connection.request(method, route, body=body, headers=merged)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_xml_resource_by_id_exposes_metadata_only(self):
        status, _, body = self.call('GET', '/api/v1/files/xml/file-1')
        self.assertEqual(status, 200, body)
        item = json.loads(body)
        self.assertEqual(item['id'], 'file-1')
        self.assertEqual(set(item), {'id', 'name', 'libraryPath', 'revision'})
        self.assertEqual(self.call('GET', '/api/v1/files/xml/missing')[0], 404)
        self.assertEqual(self.call('GET', '/api/v1/files/xml/file-1', authenticated=False)[0], 401)

    def test_xml_generation_uses_id_from_path_and_rejects_body_id(self):
        route = '/api/v1/files/xml/file-1/new'
        status, _, body = self.call('POST', route, {'recordCount': 2, 'delivery': 'inline'})
        self.assertEqual(status, 200, body)
        self.assertEqual(body.count(b'<Record>'), 2)
        self.assertEqual(self.call('POST', route, {'fileId': 'other', 'recordCount': 2})[0], 400)
        self.assertEqual(self.call('POST', '/api/v1/files/xml/missing/new', {'recordCount': 2})[0], 404)

    def test_content_delivery_returns_xml_without_publishing_or_logging_it(self):
        status, _, body = self.call('POST', '/api/v1/files/xml/file-1/new',
                                    {'recordCount': 3, 'delivery': 'content'})
        self.assertEqual(status, 200, body)
        result = json.loads(body)
        self.assertEqual(result['delivery'], 'content')
        generated = result['files'][0]
        content = generated['content'].encode('utf-8')
        self.assertTrue(generated['fileName'].endswith('.xml'))
        self.assertEqual(generated['records'], 3)
        self.assertEqual(generated['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(generated['sizeBytes'], len(content))
        self.assertEqual(list((self.root / 'output').iterdir()), [])
        logs = ''.join(path.read_text(encoding='utf-8') for path in (self.root / 'logs').glob('*.txt'))
        self.assertNotIn('content', logs)
        self.assertNotIn('<Document', logs)

    def test_return_uses_supplied_values_and_selects_all_or_first_input_record(self):
        from contextlib import closing
        import sqlite3
        from xml.dom import minidom
        with closing(sqlite3.connect(self.root / 'source.sqlite3')) as database, database:
            config = json.loads(database.execute('SELECT config_json FROM variations').fetchone()[0])
            field = json.dumps([{'ns': '', 'name': name, 'index': 1} for name in ('Document', 'Record', 'Value')])
            for model in config['returnModels']:
                model['rules'] = {field: {'generator': {'type': 'copy', 'path': field}}}
            database.execute('UPDATE variations SET config_json=?', (json.dumps(config),))
        source = '<Document><Record><Value>CLIENTE-UM</Value></Record><Record><Value>CLIENTE-DOIS</Value></Record></Document>'
        for selection, expected in [('all', ['CLIENTE-UM', 'CLIENTE-DOIS']), ('first', ['CLIENTE-UM'])]:
            for composition in ('apart', 'mixed'):
                with self.subTest(inputRecords=selection, composition=composition):
                    payload = {'inputXml': source, 'inputRecords': selection, 'composition': composition,
                               'returnSelection': {'type': 'all'}, 'delivery': 'content'}
                    status, _, body = self.call('POST', '/api/v1/files/xml/file-1/return', payload)
                    self.assertEqual(status, 200, body)
                    result = json.loads(body)
                    self.assertEqual(result['inputRecords'], selection)
                    self.assertEqual(len(result['files']), 2 if composition == 'apart' else 1)
                    for generated in result['files']:
                        doc = minidom.parseString(generated['content'])
                        values = [node.firstChild.data for node in doc.getElementsByTagName('Value')]
                        self.assertEqual(values, expected if composition == 'apart' else [v for v in expected for _ in range(2)])
                    if composition == 'mixed':
                        self.assertEqual(result['recordsPerReturn'], len(expected))
                        self.assertEqual(result['totalRecords'], len(expected) * 2)
        self.assertEqual(list((self.root / 'output').iterdir()), [])
        logs = ''.join(path.read_text(encoding='utf-8') for path in (self.root / 'logs').glob('*.txt'))
        self.assertNotIn('CLIENTE-UM', logs)
        self.assertNotIn('CLIENTE-DOIS', logs)

    def test_return_content_uses_explicit_input_and_defaults_to_all_records(self):
        route = '/api/v1/files/xml/file-1/return'
        payload = {'returnSelection': {'type': 'all'}, 'inputXml': self.source_xml, 'delivery': 'content'}
        headers = {'Idempotency-Key': 'return-content'}
        status, _, body = self.call('POST', route, payload, headers)
        self.assertEqual(status, 200, body)
        result = json.loads(body)
        self.assertEqual(result['inputRecords'], 'all')
        self.assertIn('example', result['files'][0]['content'])
        status, replay_headers, replay = self.call('POST', route, payload, headers)
        self.assertEqual(status, 200)
        self.assertEqual(replay, body)
        self.assertEqual(replay_headers['X-Idempotent-Replay'], 'true')
        self.assertEqual(self.call('POST', route, dict(payload, inputRecords='first'), headers)[0], 409)
        for selection in (None, True, 'last', 1):
            self.assertEqual(self.call('POST', route, dict(payload, inputRecords=selection))[0], 400)
        self.assertEqual(self.call('POST', '/api/v1/files/xml/file-1/new',
                                  {'recordCount': 1, 'inputRecords': 'first'})[0], 400)

    def test_only_supported_format_routes_are_available(self):
        for route in ['/api/v1/files', '/api/v1/new', '/api/v1/return',
                      '/api/v1/files/file-1/modes', '/api/v1/files/json',
                      '/api/v1/files/csv/file-1', '/api/v1/files/cnab/file-1/new']:
            with self.subTest(route=route):
                self.assertEqual(self.call('GET', route)[0], 404)

    def test_swagger_and_openapi_are_local_and_anonymous(self):
        for route in ['/', '/swagger', '/swagger/', '/swagger/index.html']:
            with self.subTest(route=route):
                status, headers, body = self.call('GET', route, authenticated=False)
                self.assertEqual(status, 200, body)
                self.assertIn('text/html', headers['Content-Type'])
                self.assertIn(b'/swagger/swagger-ui-bundle.js', body)
        for name, media in [('swagger-ui-bundle.js', 'javascript'), ('swagger-ui.css', 'text/css')]:
            status, headers, body = self.call('GET', '/swagger/' + name, authenticated=False)
            self.assertEqual(status, 200)
            self.assertIn(media, headers['Content-Type'])
            self.assertGreater(len(body), 1000)
        status, _, body = self.call('GET', '/openapi.json', authenticated=False)
        self.assertEqual(status, 200, body)
        spec = json.loads(body)
        self.assertIn('/api/v1/files/xml/{fileId}/new', spec['paths'])
        self.assertNotIn('/api/v1/new', spec['paths'])
        self.assertEqual(spec['servers'], [{'url': '/'}])
        self.assertEqual(spec['components']['securitySchemes']['ApiKey']['name'], 'X-API-Key')
        self.assertNotIn(self.key.encode(), body)
        self.assertNotIn(str(self.root).encode(), body)
        self.assertEqual(self.call('GET', '/swagger/v1/swagger.json', authenticated=False)[2], body)
        status, headers, body = self.call('HEAD', '/swagger/', authenticated=False)
        self.assertEqual(status, 200)
        self.assertGreater(int(headers['Content-Length']), 0)
        self.assertEqual(body, b'')
        self.assertEqual(self.call('POST', '/openapi.json', {}, authenticated=False)[0], 405)
        self.assertEqual(self.call('GET', '/swagger/../config.json')[0], 404)

    def test_health_root_and_authentication_and_methods(self):
        status, headers, body = self.call('GET', '/health', authenticated=False)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'ok')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        status, _, body = self.call('GET', '/api/v1/files/xml', authenticated=False)
        self.assertEqual(status, 401)
        self.assertNotIn(str(self.root).encode(), body)
        status, headers, _ = self.call('POST', '/api/v1/files/xml', {})
        self.assertEqual(status, 405)
        self.assertEqual(headers['Allow'], 'GET')
        self.assertEqual(self.call('GET', '/api/v1/health')[0], 404)

    def test_catalog_and_revision(self):
        status, _, body = self.call('GET', '/api/v1/files/xml')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['items'][0]['id'], 'file-1')
        status, _, body = self.call('GET', '/api/v1/files/xml/file-1/modes')
        self.assertEqual(status, 200)
        self.assertEqual([item['id'] for item in json.loads(body)['items']], ['new', 'return'])
        status, _, body = self.call('POST', '/api/v1/files/xml/file-1/new', {'recordCount': 1, 'expectedRevision': 999})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)['error']['code'], 'REVISION_MISMATCH')

    def test_new_inline_hash_and_count_and_idempotency(self):
        from xml.dom import minidom
        payload = {'recordCount': 3, 'delivery': 'inline'}
        headers = {'Idempotency-Key': 'new-inline'}
        status, response_headers, body = self.call('POST', '/api/v1/files/xml/file-1/new', payload, headers)
        self.assertEqual(status, 200, body)
        self.assertEqual(response_headers['X-Mockaize-SHA256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(int(response_headers['X-Mockaize-Size-Bytes']), len(body))
        self.assertEqual(len(minidom.parseString(body).getElementsByTagName('Record')), 3)
        status, replay_headers, replay = self.call('POST', '/api/v1/files/xml/file-1/new', payload, headers)
        self.assertEqual(status, 200)
        self.assertEqual(body, replay)
        self.assertEqual(replay_headers['X-Idempotent-Replay'], 'true')
        status, _, _ = self.call('POST', '/api/v1/files/xml/file-1/new', dict(payload, recordCount=4), headers)
        self.assertEqual(status, 409)
        self.assertEqual(list((self.root / 'output').iterdir()), [])

    def test_return_apart_directory_and_mixed_inline(self):
        from xml.dom import minidom
        payload = {'returnSelection': {'type': 'all'}, 'inputXml': self.source_xml}
        status, _, body = self.call('POST', '/api/v1/files/xml/file-1/return', payload)
        self.assertEqual(status, 200, body)
        files = json.loads(body)['files']
        self.assertEqual(len(files), 2)
        for item in files:
            data = (self.root / 'output' / item['fileName']).read_bytes()
            self.assertEqual(item['sha256'], hashlib.sha256(data).hexdigest())
        status, _, body = self.call('POST', '/api/v1/files/xml/file-1/return', dict(payload, composition='mixed', delivery='inline'))
        self.assertEqual(status, 200, body)
        self.assertEqual(len(minidom.parseString(body).getElementsByTagName('Record')), 2)

    def test_invalid_structure_publishes_nothing_and_file_origin_is_rejected(self):
        payload = {'returnSelection': {'type': 'all'}}
        path = self.root / 'input' / 'entrada.xml'
        path.write_text('<Document><Record><Other/></Record></Document>')
        for origin, expected in [({'inputXml': path.read_text()}, 422), ({'inputFilePath': str(path)}, 400)]:
            status, _, body = self.call('POST', '/api/v1/files/xml/file-1/return', dict(payload, **origin))
            self.assertEqual(status, expected, body)
            self.assertEqual(json.loads(body)['error']['code'], 'INPUT_XML_STRUCTURE_MISMATCH' if expected == 422 else 'INVALID_REQUEST')
        self.assertEqual(list((self.root / 'output').iterdir()), [])

    def test_body_validation_unknown_fields_null_boolean_and_delivery(self):
        for payload in [{'recordCount': True},
                        {'recordCount': 1, 'extra': 1},
                        {'returnSelection': {'type': 'all'}, 'inputXml': None}]:
            operation = 'return' if 'returnSelection' in payload else 'new'
            self.assertEqual(self.call('POST', '/api/v1/files/xml/file-1/' + operation, payload)[0], 400)
        status, _, _ = self.call('POST', '/api/v1/files/xml/file-1/return', {'returnSelection': {'type': 'all'}, 'inputXml': self.source_xml, 'delivery': 'inline'})
        self.assertEqual(status, 422)
        status, _, body = self.call('POST', '/api/v1/files/xml/file-1/return', {
            'returnSelection': {'type': 'ids', 'ids': ['unknown']}, 'inputXml': self.source_xml})
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)['error']['code'], 'RETURN_NOT_FOUND')

    def test_health_degrades_when_database_is_lost(self):
        (self.root / 'source.sqlite3').unlink()
        status, _, body = self.call('GET', '/health', authenticated=False)
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body)['status'], 'unavailable')

    def test_health_degrades_when_output_is_unwritable(self):
        from mockaize_api.preflight import PreflightError
        with patch('mockaize_api.runtime._check_directories', side_effect=PreflightError('outputDirectory', 'Sem acesso.')):
            self.assertEqual(self.call('GET', '/health')[0], 503)

    def test_retry_same_idempotency_key_after_temporary_saturation(self):
        app = self.server.application
        for _ in range(app.policy.generation_concurrency):
            app.generation_slots.acquire()
        payload = {'recordCount': 1, 'delivery': 'inline'}
        headers = {'Idempotency-Key': 'temporary-load'}
        try:
            self.assertEqual(self.call('POST', '/api/v1/files/xml/file-1/new', payload, headers)[0], 429)
        finally:
            for _ in range(app.policy.generation_concurrency):
                app.generation_slots.release()
        self.assertEqual(self.call('POST', '/api/v1/files/xml/file-1/new', payload, headers)[0], 200)

    def test_slow_client_socket_is_closed_during_stop(self):
        client = socket.create_connection(self.server.server_address)
        self.addCleanup(client.close)
        client.sendall(b'POST /api/v1/files/xml/file-1/new HTTP/1.0\r\n')
        time.sleep(0.03)
        started = time.monotonic()
        self.server.close_clients()
        client.settimeout(2)
        try:
            self.assertEqual(client.recv(1024), b'')
        except ConnectionResetError:
            pass
        self.assertLess(time.monotonic() - started, 2)

    def test_media_size_rate_and_log_dependency_errors(self):
        self.assertEqual(self.call('POST', '/api/v1/files/xml/file-1/new', {}, {'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.call('POST', '/api/v1/files/xml/file-1/return', {
            'returnSelection': {'type': 'all'}, 'inputXml': 'x' * 2_000_001})[0], 413)
        app = self.server.application
        for _ in range(app.policy.requests_per_second):
            app.rate.append(time.monotonic())
        self.assertEqual(self.call('GET', '/api/v1/files/xml')[0], 429)
        from mockaize_api.errors import ApiError
        with patch.object(app.log, 'write', side_effect=ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Log indisponível.')):
            self.assertEqual(self.call('GET', '/health')[0], 503)

    def test_logs_never_contain_key_xml_or_local_path(self):
        self.call('GET', '/health')
        self.call('POST', '/api/v1/files/xml/file-1/return', {'returnSelection': {'type': 'all'}, 'inputXml': '<secret>private</secret>'})
        logs = ''.join(path.read_text(encoding='utf-8') for path in (self.root / 'logs').glob('*.txt'))
        self.assertNotIn(self.key, logs)
        self.assertNotIn('<secret>', logs)
        self.assertNotIn(str(self.root), logs)

    def assert_envelope(self, response, expected_status):
        status, headers, content = response
        self.assertEqual(status, expected_status, content)
        self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
        value = json.loads(content)
        self.assertEqual(set(value['error']), {'code', 'message', 'traceId'})
        self.assertEqual(value['error']['traceId'], headers['X-Request-ID'])
        self.assertNotIn('status', value)
        self.assertNotIn(self.key.encode(), content)
        self.assertNotIn(str(self.root).encode(), content)
        return value

    def log_entries(self):
        return [json.loads(line) for path in (self.root / 'logs').glob('*.txt')
                for line in path.read_text(encoding='utf-8').splitlines()]

    def login(self):
        response = self.call('POST', '/api/v1/auth/token', {})
        self.assertEqual(response[0], 200, response[2])
        return json.loads(response[2])['access_token']

    def test_login_bearer_and_authentication_event_have_no_identity_or_secret(self):
        original_files = set(self.root.iterdir())
        original_credentials = (self.root / 'credentials.json').read_bytes()
        token = self.login()
        self.assertEqual(set(self.root.iterdir()), original_files)
        self.assertEqual((self.root / 'credentials.json').read_bytes(), original_credentials)
        response = self.call('GET', '/api/v1/files/xml',
                             headers={'Authorization': 'Bearer ' + token}, authenticated=False)
        self.assertEqual(response[0], 200, response[2])
        entries = self.log_entries()
        login = next(entry for entry in entries if entry.get('event') == 'LOGIN_SUCCESS')
        self.assertEqual(login['route'], '/api/v1/auth/token')
        self.assertTrue(login['authenticated'])
        self.assertEqual(login['authMethod'], 'apiKey')
        self.assertTrue(entries[-1]['authenticated'])
        self.assertEqual(entries[-1]['authMethod'], 'bearer')
        logs = json.dumps(entries)
        self.assertNotIn(token, logs)
        self.assertNotIn(self.key, logs)
        self.assertNotIn('access_token', logs)
        self.assertNotIn('user', logs)

    def test_optional_auth_allows_absence_but_never_downgrades_bad_credentials(self):
        from dataclasses import replace
        from mockaize_api.config import Authentication
        self.server.application.config = replace(self.server.application.config,
                                                 authentication=Authentication(required=False))
        self.assertEqual(self.call('GET', '/api/v1/files/xml', authenticated=False)[0], 200)
        self.assertEqual(self.log_entries()[-1]['authMethod'], 'none')
        self.assertFalse(self.log_entries()[-1]['authenticated'])
        self.assert_envelope(self.call('GET', '/api/v1/files/xml', headers={'X-API-Key': 'wrong'}), 401)
        self.assert_envelope(self.call('GET', '/api/v1/files/xml', authenticated=False,
                                      headers={'Authorization': 'Bearer invalid'}), 401)
        self.assert_envelope(self.call('POST', '/api/v1/auth/token', {}, authenticated=False), 401)
        self.assert_envelope(self.call('GET', '/api/v1/files/xml', headers={'Authorization': 'Bearer x'}), 400)
        self.assertEqual(self.call('GET', '/health', authenticated=False)[0], 200)
        self.assertEqual(self.call('GET', '/', authenticated=False)[0], 200)

    def test_login_rejects_body_fields_bearer_duplicate_headers_and_oversize_body(self):
        token = self.login()
        for body in ([], None, {'username': 'PRIVATE'}, {'refresh_token': token}):
            response = self.call('POST', '/api/v1/auth/token', body,
                                 headers={'Content-Type': 'application/json'})
            self.assertEqual(response[0], 400, response[2])
        self.assert_envelope(self.call('POST', '/api/v1/auth/token', {}, authenticated=False,
                                      headers={'Authorization': 'Bearer ' + token}), 401)
        self.assert_envelope(self.call('POST', '/api/v1/auth/token', {'large': 'x' * 4096}), 413)
        self.assert_envelope(self.call('GET', '/api/v1/auth/token'), 405)
        for name, values in [('X-API-Key', [self.key, self.key]),
                             ('Authorization', ['Bearer ' + token, 'Bearer ' + token])]:
            connection = HTTPConnection(*self.server.server_address, timeout=5)
            try:
                connection.putrequest('GET', '/api/v1/files/xml')
                for value in values:
                    connection.putheader(name, value)
                connection.endheaders()
                response = connection.getresponse()
                self.assertEqual(response.status, 400, response.read())
            finally:
                connection.close()

    def test_bearer_expiry_restart_rotation_and_replay_use_current_authentication(self):
        app = self.server.application
        now = [1000.0]
        app.auth.clock = lambda: now[0]
        token = self.login()
        payload = {'recordCount': 1, 'expectedRevision': 999}
        route = '/api/v1/files/xml/file-1/new'
        original = self.call('POST', route, payload, {'Idempotency-Key': 'auth-replay'})
        replay = self.call('POST', route, payload, {'Idempotency-Key': 'auth-replay',
                           'Authorization': 'Bearer ' + token}, authenticated=False)
        self.assertEqual(replay[2], original[2])
        self.assertEqual(self.log_entries()[-1]['authMethod'], 'bearer')
        now[0] += 1800
        self.assert_envelope(self.call('GET', '/api/v1/files/xml', authenticated=False,
                                      headers={'Authorization': 'Bearer ' + token}), 401)
        now[0] = 1000.0
        token = self.login()
        self.key = create_credentials(self.config_path, rotate=True)
        self.assert_envelope(self.call('GET', '/api/v1/files/xml', authenticated=False,
                                      headers={'Authorization': 'Bearer ' + token}), 401)
        self.assertEqual(self.call('GET', '/api/v1/files/xml')[0], 200)
        token = self.login()
        app.auth = type(app.auth)(self.config_path)
        self.assert_envelope(self.call('GET', '/api/v1/files/xml', authenticated=False,
                                      headers={'Authorization': 'Bearer ' + token}), 401)

    def test_public_error_envelopes_cover_http_status_and_log_correlation(self):
        route = '/api/v1/files/xml/file-1/new'
        responses = [
            (self.call('POST', route, {'recordCount': True}), 400),
            (self.call('GET', '/api/v1/files/xml', authenticated=False), 401),
            (self.call('GET', '/api/v1/files/xml/missing'), 404),
            (self.call('POST', '/api/v1/files/xml', {}), 405),
            (self.call('POST', route, {'recordCount': 1, 'expectedRevision': 999}), 409),
            (self.call('POST', route, {}, {'Content-Type': 'text/plain'}), 415),
            (self.call('POST', '/api/v1/files/xml/file-1/return',
                       {'returnSelection': {'type': 'all'}, 'inputXml': '<wrong/>'}), 422),
        ]
        responses.append((self.call('POST', '/api/v1/files/xml/file-1/return',
                                    {'returnSelection': {'type': 'all'}, 'inputXml': 'x' * 2000001}), 413))
        with patch.object(self.server.application, 'rate_check', side_effect=ApiError(429, 'RATE_LIMITED', 'Aguarde.')):
            response = self.call('GET', '/api/v1/files/xml')
            self.assertEqual(response[1]['Retry-After'], '1')
            responses.append((response, 429))
        with patch('mockaize_api.runtime.run_engine', side_effect=RuntimeError('PRIVATE-EXCEPTION')):
            responses.append((self.call('POST', route, {'recordCount': 1}), 500))
        with patch.object(self.server.application.catalog, 'file',
                          side_effect=ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Indisponível.')):
            responses.append((self.call('GET', '/api/v1/files/xml/file-1'), 503))
        entries = {entry['requestId']: entry for entry in self.log_entries()}
        for response, expected in responses:
            with self.subTest(status=expected):
                value = self.assert_envelope(response, expected)
                error = value['error']
                self.assertEqual(entries[error['traceId']]['code'], error['code'])
                self.assertNotIn(b'PRIVATE-EXCEPTION', response[2])

    def test_error_replay_preserves_original_body_trace_and_records_current_attempt(self):
        payload = {'recordCount': 1, 'expectedRevision': 999}
        route = '/api/v1/files/xml/file-1/new'
        headers = {'Idempotency-Key': 'error-replay'}
        original = self.call('POST', route, payload, headers)
        original_id = self.assert_envelope(original, 409)['error']['traceId']
        replay = self.call('POST', route, payload, headers)
        self.assertEqual(replay[2], original[2])
        self.assertEqual(replay[1]['X-Request-ID'], original_id)
        self.assertEqual(replay[1]['X-Idempotent-Replay'], 'true')
        entry = self.log_entries()[-1]
        self.assertNotEqual(entry['requestId'], original_id)
        self.assertEqual(entry['responseTraceId'], original_id)
        self.assertEqual(entry['replayOfTraceId'], original_id)
        self.assertEqual(entry['code'], 'REVISION_MISMATCH')

    def test_legacy_persisted_error_replay_keeps_bytes_and_original_request_id(self):
        body = json.dumps({'code': 'LEGACY_FAILURE', 'status': 422,
                           'requestId': 'legacy-trace', 'detail': 'Falha anterior.'}).encode()
        response = {'status': 422, 'headers': {'Content-Type': 'application/problem+json; charset=utf-8'},
                    'body': body}
        with patch.object(self.server.application.state, 'begin', return_value=response):
            status, headers, actual = self.call('POST', '/api/v1/files/xml/file-1/new',
                                               {'recordCount': 1}, {'Idempotency-Key': 'legacy-error'})
        self.assertEqual(status, 422)
        self.assertEqual(actual, body)
        self.assertEqual(headers['X-Request-ID'], 'legacy-trace')
        self.assertEqual(headers['Content-Type'], 'application/problem+json; charset=utf-8')
        entry = self.log_entries()[-1]
        self.assertNotEqual(entry['requestId'], 'legacy-trace')
        self.assertEqual(entry['responseTraceId'], 'legacy-trace')
        self.assertEqual(entry['replayOfTraceId'], 'legacy-trace')
        self.assertEqual(entry['code'], 'LEGACY_FAILURE')

    def test_connection_saturation_returns_json_and_logs_its_trace(self):
        slots = self.server.application.policy.maximum_connections
        for _ in range(slots):
            self.server.connections.acquire()
        try:
            response = self.call('GET', '/health', authenticated=False)
        finally:
            for _ in range(slots):
                self.server.connections.release()
        value = self.assert_envelope(response, 429)
        self.assertEqual(response[1]['Retry-After'], '1')
        self.server.rejection_events.join()
        self.assertEqual(self.log_entries()[-1]['requestId'], value['error']['traceId'])

    def test_slow_rejection_log_does_not_block_accept_or_server_close(self):
        entered, release = threading.Event(), threading.Event()
        writer = self.server.application.log.write

        def slow_write(**entry):
            if entry.get('method') == 'UNPARSED':
                entered.set()
                release.wait(10)
            writer(**entry)

        slots = self.server.application.policy.maximum_connections
        for _ in range(slots):
            self.server.connections.acquire()
        try:
            with patch.object(self.server.application.log, 'write', side_effect=slow_write):
                started = time.monotonic()
                self.assert_envelope(self.call('GET', '/health', authenticated=False), 429)
                self.assertLess(time.monotonic() - started, 2)
                self.assertTrue(entered.wait(2), 'The rejection log worker did not start.')
                for _ in range(slots):
                    self.server.connections.release()
                slots = 0
                started = time.monotonic()
                self.assertEqual(self.call('GET', '/', authenticated=False)[0], 200)
                self.assertLess(time.monotonic() - started, 2)
                self.assertFalse(release.is_set())
                capacity = self.server.application.policy.maximum_connections
                for index in range(capacity):
                    self.assertTrue(self.server._queue_rejection(f'queued-{index}'))
                self.assertFalse(self.server._queue_rejection('overflow'))
                self.assertEqual(self.server.rejection_events.qsize(), capacity)
                for _ in range(capacity):
                    self.server.connections.acquire()
                try:
                    self.assert_envelope(self.call('GET', '/health', authenticated=False), 503)
                finally:
                    for _ in range(capacity):
                        self.server.connections.release()
                self.server.shutdown()
                self.thread.join(2)
                started = time.monotonic()
                self.server.server_close()
                self.assertLess(time.monotonic() - started, 1)
        finally:
            release.set()
            for _ in range(slots):
                self.server.connections.release()

    def test_parser_and_unknown_method_errors_use_sanitized_json(self):
        response = self.call('PRIVATE-METHOD', '/health', authenticated=False)
        self.assert_envelope(response, 501)
        client = socket.create_connection(self.server.server_address, timeout=5)
        try:
            client.sendall(b'GET /PRIVATE-PATH HTTP/1.invalid\r\n\r\n')
            from http.client import HTTPResponse
            parsed = HTTPResponse(client)
            parsed.begin()
            response = (parsed.status, dict(parsed.getheaders()), parsed.read())
        finally:
            client.close()
        self.assert_envelope(response, 400)
        content = response[2].decode() + json.dumps(self.log_entries())
        self.assertNotIn('PRIVATE-PATH', content)
        self.assertNotIn('PRIVATE-METHOD', content)


class ErrorEnvelopeTests(unittest.TestCase):
    def test_error_status_stays_only_in_http_for_every_representative_code(self):
        for status in (400, 401, 403, 404, 405, 409, 413, 415, 422, 429, 500, 503):
            with self.subTest(status=status):
                response = _problem(ApiError(status, 'PUBLIC_CODE', 'Mensagem.'), 'trace')
                self.assertEqual(response['status'], status)
                self.assertEqual(set(json.loads(response['body'])), {'error'})
                self.assertEqual(response['headers']['X-Request-ID'], 'trace')

    def test_only_documented_typed_extensions_are_exposed_at_root(self):
        error = ApiError(422, 'INPUT_XML_STRUCTURE_MISMATCH', 'Estrutura divergente.',
                         xmlPath='Document/Record', reason='namespace-divergente',
                         error={'code': 'OVERRIDE'}, requestId='OVERRIDE', secret='PRIVATE')
        response = _problem(error, 'original-trace')
        self.assertEqual(response['headers']['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(json.loads(response['body']), {
            'error': {'code': error.code, 'message': error.detail, 'traceId': 'original-trace'},
            'xmlPath': 'Document/Record', 'reason': 'namespace-divergente'})
        error.extensions.update(xmlPath={'PRIVATE': True}, reason=['PRIVATE'])
        self.assertEqual(set(json.loads(_problem(error, 'trace')['body'])), {'error'})
