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
from mockaize_api.runtime import ApiServer, Application
from mockaize_api.security import create_credentials


class HttpTests(unittest.TestCase):
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

    def test_health_root_and_authentication_and_methods(self):
        status, headers, body = self.call('GET', '/health', authenticated=False)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'ok')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        status, _, body = self.call('GET', '/api/v1/files', authenticated=False)
        self.assertEqual(status, 401)
        self.assertNotIn(str(self.root).encode(), body)
        status, headers, _ = self.call('POST', '/api/v1/files', {})
        self.assertEqual(status, 405)
        self.assertEqual(headers['Allow'], 'GET')
        self.assertEqual(self.call('GET', '/api/v1/health')[0], 404)

    def test_catalog_and_revision(self):
        status, _, body = self.call('GET', '/api/v1/files')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['items'][0]['id'], 'file-1')
        status, _, body = self.call('GET', '/api/v1/files/file-1/modes')
        self.assertEqual(status, 200)
        self.assertEqual([item['id'] for item in json.loads(body)['items']], ['new', 'return'])
        status, _, body = self.call('POST', '/api/v1/new', {'fileId': 'file-1', 'recordCount': 1, 'expectedRevision': 999})
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)['code'], 'REVISION_MISMATCH')

    def test_new_inline_hash_and_count_and_idempotency(self):
        from xml.dom import minidom
        payload = {'fileId': 'file-1', 'recordCount': 3, 'delivery': 'inline'}
        headers = {'Idempotency-Key': 'new-inline'}
        status, response_headers, body = self.call('POST', '/api/v1/new', payload, headers)
        self.assertEqual(status, 200, body)
        self.assertEqual(response_headers['X-Mockaize-SHA256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(int(response_headers['X-Mockaize-Size-Bytes']), len(body))
        self.assertEqual(len(minidom.parseString(body).getElementsByTagName('Record')), 3)
        status, replay_headers, replay = self.call('POST', '/api/v1/new', payload, headers)
        self.assertEqual(status, 200)
        self.assertEqual(body, replay)
        self.assertEqual(replay_headers['X-Idempotent-Replay'], 'true')
        status, _, _ = self.call('POST', '/api/v1/new', dict(payload, recordCount=4), headers)
        self.assertEqual(status, 409)
        self.assertEqual(list((self.root / 'output').iterdir()), [])

    def test_return_apart_directory_and_mixed_inline(self):
        from xml.dom import minidom
        payload = {'fileId': 'file-1', 'returnSelection': {'type': 'all'}}
        status, _, body = self.call('POST', '/api/v1/return', payload)
        self.assertEqual(status, 200, body)
        files = json.loads(body)['files']
        self.assertEqual(len(files), 2)
        for item in files:
            data = (self.root / 'output' / item['fileName']).read_bytes()
            self.assertEqual(item['sha256'], hashlib.sha256(data).hexdigest())
        status, _, body = self.call('POST', '/api/v1/return', dict(payload, composition='mixed', delivery='inline'))
        self.assertEqual(status, 200, body)
        self.assertEqual(len(minidom.parseString(body).getElementsByTagName('Record')), 2)

    def test_invalid_structure_publishes_nothing_for_all_input_origins(self):
        payload = {'fileId': 'file-1', 'returnSelection': {'type': 'all'}}
        path = self.root / 'input' / 'entrada.xml'
        path.write_text('<Document><Record><Other/></Record></Document>')
        for origin in [{'inputXml': path.read_text()}, {'inputFilePath': str(path)}]:
            status, _, body = self.call('POST', '/api/v1/return', dict(payload, **origin))
            self.assertEqual(status, 422, body)
            self.assertEqual(json.loads(body)['code'], 'INPUT_XML_STRUCTURE_MISMATCH')
        self.assertEqual(list((self.root / 'output').iterdir()), [])

    def test_body_validation_unknown_fields_null_boolean_and_delivery(self):
        for payload in [{'fileId': 'file-1', 'recordCount': True},
                        {'fileId': 'file-1', 'recordCount': 1, 'extra': 1},
                        {'fileId': 'file-1', 'returnSelection': {'type': 'all'}, 'inputXml': None}]:
            operation = 'return' if 'returnSelection' in payload else 'new'
            self.assertEqual(self.call('POST', '/api/v1/' + operation, payload)[0], 400)
        status, _, _ = self.call('POST', '/api/v1/return', {'fileId': 'file-1', 'returnSelection': {'type': 'all'}, 'delivery': 'inline'})
        self.assertEqual(status, 422)
        status, _, body = self.call('POST', '/api/v1/return', {
            'fileId': 'file-1', 'returnSelection': {'type': 'ids', 'ids': ['unknown']}})
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)['code'], 'RETURN_NOT_FOUND')

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
        payload = {'fileId': 'file-1', 'recordCount': 1, 'delivery': 'inline'}
        headers = {'Idempotency-Key': 'temporary-load'}
        try:
            self.assertEqual(self.call('POST', '/api/v1/new', payload, headers)[0], 429)
        finally:
            for _ in range(app.policy.generation_concurrency):
                app.generation_slots.release()
        self.assertEqual(self.call('POST', '/api/v1/new', payload, headers)[0], 200)

    def test_slow_client_socket_is_closed_during_stop(self):
        client = socket.create_connection(self.server.server_address)
        self.addCleanup(client.close)
        client.sendall(b'POST /api/v1/new HTTP/1.0\r\n')
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
        self.assertEqual(self.call('POST', '/api/v1/new', {}, {'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.call('POST', '/api/v1/return', {
            'fileId': 'file-1', 'returnSelection': {'type': 'all'}, 'inputXml': 'x' * 2_000_001})[0], 413)
        app = self.server.application
        for _ in range(app.policy.requests_per_second):
            app.rate.append(time.monotonic())
        self.assertEqual(self.call('GET', '/api/v1/files')[0], 429)
        from mockaize_api.errors import ApiError
        with patch.object(app.log, 'write', side_effect=ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Log indisponível.')):
            self.assertEqual(self.call('GET', '/health')[0], 503)

    def test_logs_never_contain_key_xml_or_local_path(self):
        self.call('GET', '/health')
        self.call('POST', '/api/v1/return', {'fileId': 'file-1', 'returnSelection': {'type': 'all'}, 'inputXml': '<secret>private</secret>'})
        logs = ''.join(path.read_text(encoding='utf-8') for path in (self.root / 'logs').glob('*.txt'))
        self.assertNotIn(self.key, logs)
        self.assertNotIn('<secret>', logs)
        self.assertNotIn(str(self.root), logs)
