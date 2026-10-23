"""Smoke do executável sem instalar serviço, alterar ACLs ou firewall."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
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
        save_config(config, ApiConfig(root / 'source.sqlite3', root / 'input', root / 'output',
                                     root / 'logs', port, '127.0.0.1', 'N'))
        key = create_credentials(config)
        opener = build_opener(ProxyHandler({}))
        base = f'http://127.0.0.1:{port}'
        def call(route, payload=None):
            request = Request(base + route, data=json.dumps(payload).encode() if payload is not None else None,
                              headers={'X-API-Key': key, 'Content-Type': 'application/json'})
            with opener.open(request, timeout=30) as response:
                return dict(response.headers), response.read()
        process = subprocess.Popen([str(binary), '--run', '--config', str(config)],
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    _, body = call('/health')
                    if json.loads(body)['status'] == 'ok':
                        break
                except (URLError, OSError):
                    pass
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Executável não confirmou saúde.')
                time.sleep(0.2)
            _, body = call('/api/v1/files')
            assert json.loads(body)['items'][0]['id'] == 'file-1'
            started = time.monotonic()
            headers, body = call('/api/v1/new', {'fileId': 'file-1', 'recordCount': 500, 'delivery': 'inline'})
            assert len(ET.fromstring(body).findall('Record')) == 500
            assert hashlib.sha256(body).hexdigest() == headers['X-Mockaize-SHA256']
            elapsed = time.monotonic() - started
            _, manifest = call('/api/v1/return', {'fileId': 'file-1', 'returnSelection': {'type': 'all'}})
            manifest = json.loads(manifest)
            assert len(manifest['files']) == 2
            for entry in manifest['files']:
                content = (root / 'output' / entry['fileName']).read_bytes()
                assert hashlib.sha256(content).hexdigest() == entry['sha256']
            headers, body = call('/api/v1/return', {'fileId': 'file-1', 'returnSelection': {'type': 'all'},
                                                   'composition': 'mixed', 'delivery': 'inline'})
            assert len(ET.fromstring(body).findall('Record')) == 2
            print(json.dumps({'frozenSmoke': 'passed', 'newRecords': 500,
                              'newDurationSeconds': round(elapsed, 3), 'apartFiles': 2, 'mixedRecords': 2}))
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(10)


if __name__ == '__main__':
    main()
