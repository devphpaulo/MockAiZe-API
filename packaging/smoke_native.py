"""Real native lifecycle test, permitted only on disposable GitHub Windows runners."""
import configparser
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from urllib.request import Request, ProxyHandler, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from fixtures.catalog_factory import create_catalog
from mockaize_api.config import ApiConfig, save_config
from mockaize_api.security import create_credentials
from mockaize_api.windows_ops import WindowsDriver, discover_installation


def write_request(path, values):
    parser = configparser.ConfigParser(interpolation=None)
    parser['setup'] = {key: str(value) for key, value in values.items()}
    with path.open('w', encoding='utf-16') as stream:
        parser.write(stream)


def main():
    if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Este teste privilegiado só roda no runner descartável do GitHub.')
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('O runner precisa de elevação para testar o serviço real.')
    if WindowsDriver().status() != 'absent':
        raise RuntimeError('Existe serviço homônimo; nenhuma alteração será feita.')
    repo = Path(__file__).resolve().parents[1]
    service = repo / 'build/payload/MockAiZeApiService.exe'
    setup = repo / 'release/MockAiZe-API-Setup.exe'
    with tempfile.TemporaryDirectory(prefix='mockaize-native-') as temporary:
        root = Path(temporary).resolve()
        target, data = root / 'installed', root / 'dados'
        data.mkdir()
        source = root / 'source.sqlite3'
        create_catalog(source)
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        config_path = data / 'config.json'
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        config = ApiConfig(source, data / 'Entradas', data / 'Saídas', data / 'Logs', port, '127.0.0.1', 'N')
        save_config(config_path, config)
        key = create_credentials(config_path)
        values = {**config.to_mapping(), 'installDir': str(target), 'configPath': str(config_path),
                  'origins': 'LocalSubnet'}
        request, result = root / 'request.ini', root / 'result.ini'
        write_request(request, values)

        def bridge(operation, overrides=None):
            write_request(request, {**values, **(overrides or {})})
            completed = subprocess.run([str(service), '--maintenance', operation,
                                        '--request', str(request), '--result', str(result)], timeout=120)
            parsed = configparser.ConfigParser(interpolation=None)
            parsed.read(result, encoding='utf-16')
            reply = dict(parsed['result'])
            if completed.returncode or reply.get('ok') != '1':
                reply.pop('apikey', None)
                raise RuntimeError(f'Manutenção {operation} falhou: {reply}')
            return reply

        def native(binary, phase):
            write_request(request, values)
            log = root / f'{phase}.log'
            process = subprocess.run([str(binary), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/SP-',
                                      '/NORESTART', f'/REQUEST={request}', f'/LOG={log}'], timeout=180)
            if process.returncode != 0:
                detail = log.read_text(encoding='utf-8', errors='replace')[-6000:] if log.is_file() else ''
                raise RuntimeError(f'Inno {phase} saiu com {process.returncode}: {detail}')

        def health_and_catalog(generate=False):
            opener = build_opener(ProxyHandler({}))
            for route in ('/health', '/api/v1/files'):
                with opener.open(Request(f'http://127.0.0.1:{port}{route}', headers={'X-API-Key': key}), timeout=10) as response:
                    assert response.status == 200
            assert WindowsDriver().status() == 'running'
            if generate:
                body = json.dumps({'fileId': 'file-1', 'recordCount': 3}).encode()
                with opener.open(Request(f'http://127.0.0.1:{port}/api/v1/new', data=body,
                                  headers={'X-API-Key': key, 'Content-Type': 'application/json'}), timeout=30) as response:
                    manifest = json.load(response)
                for entry in manifest['files']:
                    content = (config.output_directory / entry['fileName']).read_bytes()
                    assert hashlib.sha256(content).hexdigest() == entry['sha256']

        try:
            native(setup, 'install')
            health_and_catalog(generate=True)
            assert (target / 'MockAiZeApiConfig.exe').is_file()
            assert (target / 'MockAiZeApiUninstall.exe').is_file()
            bridge('stop')
            native(target / 'MockAiZeApiConfig.exe', 'configure')
            health_and_catalog()
            bridge('stop')
            native(setup, 'repair')
            health_and_catalog()
            native(repo / 'release/MockAiZeApiUninstall.exe', 'uninstall')
            assert WindowsDriver().status() == 'absent'
            assert config_path.exists(), 'O padrão da limpeza deve preservar os dados.'
            assert (target / 'MockAiZeApiService.exe').exists()
            reply = bridge('cleanup', {'cleanBinaries': '1', 'folderCount': '1', 'folder0': str(data)})
            assert reply['restartrequired'] == '0'
            assert not target.exists() and not data.exists()
            assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
            print(json.dumps({'nativeLifecycle': 'passed', 'install': True, 'configure': True,
                              'repair': True, 'serviceRemoved': True, 'dataPreservedByDefault': True,
                              'optInCleanup': True, 'sourceUnchanged': True}))
        finally:
            # Never touch a pre-existing or unrelated service. This target was
            # created by this test after confirming global SCM absence above.
            installed = discover_installation()
            if installed and installed.directory.resolve() == target:
                bridge('detach')


if __name__ == '__main__':
    main()
