"""Verifica serviço x64, frontends Inno, ícones e payload sem executar instaladores."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

EXECUTABLES = {'release/MockAiZe-API-Setup.exe': (True, 0x14c, 20_000_000),
               'build/payload/MockAiZeApiConfig.exe': (True, 0x14c, 3_000_000),
               'release/MockAiZeApiUninstall.exe': (True, 0x14c, 3_000_000),
               'build/payload/MockAiZeApiService.exe': (False, 0x8664, 5_000_000)}


def validate_payload(names):
    names = {name.replace('\\', '/') for name in names}
    required = {'payload/MockAiZeApiService.exe', 'payload/MockAiZeApiConfig.exe',
                'payload/MockAiZeApiUninstall.exe', 'payload/licenses/PYTHON-LICENSE.txt',
                'payload/licenses/Inno-Setup-LICENSE.txt'}
    runtimes = [name for name in names if Path(name).name.lower().startswith('python3')
                and name.lower().endswith('.dll') and Path(name).name.lower() != 'python3.dll']
    if not required.issubset(names) or len(runtimes) != 1 or not runtimes[0].startswith('payload/_internal/'):
        raise ValueError('O pacote deve conter os frontends nativos, um runtime Python e as licenças.')
    for name in names:
        parts = name.lower().split('/')
        if (any(part.startswith(('pyside', 'shiboken', 'qt6')) for part in parts)
                or ('pythonwin' in parts and 'licenses' not in parts)
                or parts[-1].startswith(('win32ui', 'libcrypto', 'libssl', '_ssl', '_hashlib'))):
            raise ValueError('Qt ou TLS opcional entrou indevidamente na distribuição HTTP nativa.')
        if ('..' in parts or 'initial-api-docs' in parts or parts[-1] in {'credentials.json', 'config.json'}
                or parts[-1].endswith(('.sqlite3', '.sqlite3-wal', '.sqlite3-shm'))):
            raise ValueError('O setup contém arquivo privado ou caminho não permitido.')


def icon_frames(path):
    content = path.read_bytes()
    reserved, kind, count = struct.unpack_from('<HHH', content)
    if reserved != 0 or kind != 1 or not count:
        raise ValueError('O ícone Windows é inválido.')
    frames = set()
    for index in range(count):
        size, offset = struct.unpack_from('<II', content, 6 + 16 * index + 8)
        frame = content[offset:offset + size]
        if len(frame) != size:
            raise ValueError('O ícone Windows está incompleto.')
        frames.add(hashlib.sha256(frame).hexdigest())
    return frames


def resource_data(pe, kind):
    values = []
    for entry in getattr(getattr(pe, 'DIRECTORY_ENTRY_RESOURCE', None), 'entries', []):
        if entry.id == kind:
            for name in entry.directory.entries:
                for language in name.directory.entries:
                    item = language.data.struct
                    values.append(pe.get_data(item.OffsetToData, item.Size))
    return values


def verify_pe(path, expected_icons, elevated, machine=0x8664):
    import pefile
    if not path.is_file():
        raise ValueError(f'Executável ausente: {path.name}. Confira o histórico do antivírus.')
    pe = pefile.PE(str(path), fast_load=True)
    try:
        if pe.FILE_HEADER.Machine != machine:
            raise ValueError(f'{path.name} possui arquitetura inesperada.')
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        actual = {hashlib.sha256(frame).hexdigest() for frame in resource_data(pe, 3)}
        if not resource_data(pe, 14) or not expected_icons.issubset(actual):
            raise ValueError(f'{path.name} não contém o ícone aprovado do MockAíZé.')
        if elevated and not any(b'requireAdministrator' in value for value in resource_data(pe, 24)):
            raise ValueError(f'{path.name} não solicita elevação do Windows.')
    finally:
        pe.close()


def verify_build(root, icon):
    expected_icons = icon_frames(icon)
    result = []
    for relative, (elevated, machine, budget) in EXECUTABLES.items():
        path = root / relative
        # Inno's loader is asInvoker and requests elevation itself according to
        # PrivilegesRequired. It does not use PyInstaller's requireAdmin manifest.
        verify_pe(path, expected_icons, elevated and machine != 0x14c, machine)
        if path.stat().st_size > budget:
            raise ValueError(f'{path.name} excede o orçamento de tamanho ({budget} bytes).')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result.append({'fileName': path.name, 'sizeBytes': path.stat().st_size,
                       'sha256': digest})
    validate_payload(['payload/' + str(path.relative_to(root / 'build/payload')).replace('\\', '/')
                      for path in (root / 'build/payload').rglob('*') if path.is_file()])
    if 'PrivilegesRequired=admin' not in (root / 'packaging/inno/common.iss').read_text(encoding='utf-8'):
        raise ValueError('Os frontends Inno devem solicitar elevação antes das operações de manutenção.')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--icon', type=Path, default=Path('src/mockaize_api/assets/mockaize.ico'))
    args = parser.parse_args()
    try:
        result = verify_build(args.root, args.icon)
    except Exception as error:
        print(f'Validação do build falhou: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'windowsBuild': 'verified', 'files': result}, indent=2))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with Path(summary).open('a', encoding='utf-8') as stream:
            stream.write('## Executáveis Windows verificados\n\nArquivo | Bytes | SHA-256\n---|---:|---\n')
            for entry in result:
                stream.write(f'{entry["fileName"]} | {entry["sizeBytes"]} | `{entry["sha256"]}`\n')
            stream.write('\nServiço x64; frontends Inno nativos; ícones, elevação, licenças e um único runtime conferidos. Sem Qt.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
