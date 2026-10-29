"""Smoke do executável sem instalar serviço, alterar ACLs ou firewall."""
import argparse
from contextlib import closing
from datetime import datetime, time as day_time, timedelta
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from fixtures.catalog_factory import create_catalog
from mockaize_api.config import ApiConfig, save_config
from mockaize_api.security import create_credentials


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        create_catalog(root / 'source.sqlite3')
        for name in ['input', 'output', 'logs']:
            (root / name).mkdir()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        config = root / 'config.json'
        values = ApiConfig(root / 'source.sqlite3', root / 'input', root / 'output',
                           root / 'logs', port, '127.0.0.1', 'N').to_mapping()
        values.update(limits={'inputXml': {'mode': 'custom', 'bytes': 3000000},
                              'records': {'mode': 'custom', 'count': 1000}},
                      cleanup={'inputs': {'mode': 'disabled'}, 'outputs': {'mode': 'age', 'days': 2},
                               'logs': {'mode': 'age', 'days': 2}})
        save_config(config, ApiConfig.from_mapping(values))
        (root / 'policy.json').write_text(json.dumps({'requests_per_second': 100}), encoding='utf-8')
        today = datetime.now().astimezone().date()
        def aged_file(relative, days):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'disposable startup fixture')
            modified = datetime.combine(today - timedelta(days=days), day_time(12)).timestamp()
            os.utime(path, (modified, modified))
            return path
        old_output = aged_file('output/nested/old.any', 3)
        old_log = aged_file('logs/other-origin.any', 3)
        old_input = aged_file('input/preserved.any', 3)
        cutoff_output = aged_file('output/cutoff.any', 2)
        key = create_credentials(config)
        opener = build_opener(ProxyHandler({}))
        base = f'http://127.0.0.1:{port}'
        def call(route, payload=None, authenticated=True, *, bearer=None, idempotency=None, expected=200):
            headers = {'Content-Type': 'application/json'}
            if bearer is not None:
                headers['Authorization'] = 'Bearer ' + bearer
            elif authenticated:
                headers['X-API-Key'] = key
            if idempotency is not None:
                headers['Idempotency-Key'] = idempotency
            request = Request(base + route, data=json.dumps(payload).encode() if payload is not None else None,
                              headers=headers)
            try:
                response = opener.open(request, timeout=65)
            except HTTPError as error:
                response = error
            with response:
                assert response.status == expected, 'Unexpected HTTP status in frozen smoke.'
                return dict(response.headers), response.read()
        def sequence():
            uri = (root / 'api-state.sqlite3').resolve().as_uri() + '?mode=ro'
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                return connection.execute('SELECT next_index FROM sequences WHERE file_id=?', ('file-1',)).fetchone()[0]
        process = subprocess.Popen([str(binary), '--run', '--config', str(config)],
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    _, body = call('/health', authenticated=False)
                    if json.loads(body)['status'] == 'ok':
                        break
                except (URLError, OSError):
                    pass
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Executável não confirmou saúde.')
                time.sleep(0.2)
            deadline = time.monotonic() + 10
            while True:
                events = []
                for path in (root / 'logs').glob('*.txt'):
                    for line in path.read_text(encoding='utf-8').splitlines():
                        try:
                            events.append(json.loads(line))
                        except ValueError:
                            pass  # A concurrent append can expose an incomplete final line.
                if any(entry.get('event') == 'HOUSEKEEPING_COMPLETED' for entry in events):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('A rodada descartável de limpeza não concluiu.')
                time.sleep(0.05)
            assert not old_output.exists() and not old_log.exists()
            assert old_input.exists() and cutoff_output.exists()
            after_startup = aged_file('output/created-after-startup.any', 3)
            _, body = call('/swagger/', authenticated=False)
            assert b'/swagger/swagger-ui-bundle.js' in body
            for name in ('swagger-ui-bundle.js', 'swagger-ui.css', 'initializer.js', 'favicon.ico'):
                _, asset = call('/swagger/' + name, authenticated=False)
                assert asset
            _, body = call('/openapi.json', authenticated=False)
            spec = json.loads(body)
            assert '/api/v1/files/xml/{fileId}/new' in spec['paths']
            assert 'content' in spec['components']['schemas']['NewXmlRequest']['properties']['delivery']['enum']
            assert {'inputXml', 'returnSelection'} <= set(spec['components']['schemas']['ReturnXmlRequest']['required'])
            _, body = call('/api/v1/auth/token', {})
            login = json.loads(body)
            assert login['token_type'] == 'Bearer' and login['expires_in'] == 1800
            token = login['access_token']
            _, body = call('/api/v1/files/xml', authenticated=False, bearer=token)
            assert json.loads(body)['items'][0]['id'] == 'file-1'
            headers, body = call('/api/v1/files/xml/file-1/return', {'returnSelection': {'type': 'all'}}, expected=400)
            error = json.loads(body)
            assert set(error['error']) == {'code', 'message', 'traceId'}
            assert error['error']['traceId'] == headers['X-Request-ID'] and 'status' not in error
            _, body = call('/api/v1/files/xml')
            assert json.loads(body)['items'][0]['id'] == 'file-1'
            _, body = call('/api/v1/files/xml/file-1')
            assert json.loads(body)['id'] == 'file-1'
            started = time.monotonic()
            headers, body = call('/api/v1/files/xml/file-1/new', {'recordCount': 1000, 'delivery': 'inline'})
            assert len(ET.fromstring(body).findall('Record')) == 1000
            assert hashlib.sha256(body).hexdigest() == headers['X-Mockaize-SHA256']
            elapsed = time.monotonic() - started
            source = '<Document><Record><Value>example</Value></Record></Document>'
            _, manifest = call('/api/v1/files/xml/file-1/return', {'inputXml': source, 'returnSelection': {'type': 'all'}})
            manifest = json.loads(manifest)
            assert len(manifest['files']) == 2
            for entry in manifest['files']:
                content = (root / 'output' / entry['fileName']).read_bytes()
                assert hashlib.sha256(content).hexdigest() == entry['sha256']
            headers, body = call('/api/v1/files/xml/file-1/return', {'inputXml': source, 'returnSelection': {'type': 'all'},
                                                   'composition': 'mixed', 'delivery': 'inline'})
            assert len(ET.fromstring(body).findall('Record')) == 2
            _, body = call('/api/v1/files/xml/file-1/return', {
                'returnSelection': {'type': 'all'}, 'delivery': 'content', 'inputRecords': 'first',
                'inputXml': '<Document><Record><Value>one</Value></Record><Record><Value>two</Value></Record></Document>'})
            result = json.loads(body)
            assert len(result['files']) == 2
            assert all(len(ET.fromstring(item['content']).findall('Record')) == 1 for item in result['files'])
            larger_input = '<Document><Record><Value>' + 'x' * 2100000 + '</Value></Record></Document>'
            _, body = call('/api/v1/files/xml/file-1/return', {'inputXml': larger_input,
                'returnSelection': {'type': 'all'}, 'composition': 'mixed', 'delivery': 'inline'})
            assert len(ET.fromstring(body).findall('Record')) == 2
            payload = {'recordCount': 1, 'delivery': 'directory'}
            _, body = call('/api/v1/files/xml/file-1/new', payload, idempotency='expired-frozen')
            artifact = root / 'output' / json.loads(body)['files'][0]['fileName']
            assert artifact.resolve().is_relative_to((root / 'output').resolve())
            artifact.unlink()
            previous_index = sequence()
            headers, body = call('/api/v1/files/xml/file-1/new', payload, idempotency='expired-frozen', expected=410)
            assert json.loads(body)['error']['code'] == 'OUTPUT_EXPIRED'
            assert json.loads(body)['error']['traceId'] == headers['X-Request-ID']
            assert sequence() == previous_index
            payload = {'recordCount': 1, 'delivery': 'content'}
            _, original = call('/api/v1/files/xml/file-1/new', payload, idempotency='content-frozen')
            _, repeated = call('/api/v1/files/xml/file-1/new', payload, idempotency='content-frozen', bearer=token)
            assert original == repeated
            assert after_startup.exists(), 'A escrita de logs/geracao nao deve iniciar outra limpeza.'
            print(json.dumps({'frozenSmoke': 'passed', 'newRecords': 1000,
                              'newDurationSeconds': round(elapsed, 3), 'apartFiles': 2, 'mixedRecords': 2,
                              'bearerLogin': True, 'mandatoryReturnInput': True, 'startupCleanup': True,
                              'expiredReplayWithoutAdvance': True, 'contentReplay': True,
                              'customInputBytes': 3000000}))
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(10)


if __name__ == '__main__':
    main()
