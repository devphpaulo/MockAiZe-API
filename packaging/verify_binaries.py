"""Verifica PE x64, ícone, UAC e payload sem executar instaladores elevados."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

EXECUTABLES = {'MockAiZe-API-Setup.exe': True, 'MockAiZeApiConfig.exe': True,
               'MockAiZeApiUninstall.exe': True,
               'MockAiZeApiService/MockAiZeApiService.exe': False}


def validate_payload(names):
    names = {name.replace('\\', '/') for name in names}
    required = {'payload/MockAiZeApiService.exe', 'payload/MockAiZeApiConfig.exe',
                'payload/MockAiZeApiUninstall.exe', 'mockaize_api/assets/mockaize-favicon.png',
                'payload/licenses/free-software-terms/LGPL-3.0.txt'}
    if not required.issubset(names) or not any(
            name.startswith('payload/_internal/python') and name.endswith('.dll') for name in names):
        raise ValueError('O setup não contém todos os executáveis, runtime, ícone e licenças.')
    for name in names:
        parts = name.lower().split('/')
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


def verify_pe(path, expected_icons, elevated):
    import pefile
    if not path.is_file():
        raise ValueError(f'Executável ausente: {path.name}. Confira o histórico do antivírus.')
    pe = pefile.PE(str(path), fast_load=True)
    try:
        if pe.FILE_HEADER.Machine != 0x8664:
            raise ValueError(f'{path.name} não é um executável Windows x64.')
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        actual = {hashlib.sha256(frame).hexdigest() for frame in resource_data(pe, 3)}
        if not resource_data(pe, 14) or not expected_icons.issubset(actual):
            raise ValueError(f'{path.name} não contém o ícone aprovado do MockAíZé.')
        if elevated and not any(b'requireAdministrator' in value for value in resource_data(pe, 24)):
            raise ValueError(f'{path.name} não solicita elevação do Windows.')
    finally:
        pe.close()


def verify_build(dist, icon):
    from PyInstaller.archive.readers import CArchiveReader
    expected_icons = icon_frames(icon)
    result = []
    for relative, elevated in EXECUTABLES.items():
        path = dist / relative
        verify_pe(path, expected_icons, elevated)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result.append({'fileName': path.name, 'sizeBytes': path.stat().st_size,
                       'sha256': digest})
    validate_payload(CArchiveReader(str(dist / 'MockAiZe-API-Setup.exe')).toc)
    for name in ['MockAiZeApiConfig.exe', 'MockAiZeApiUninstall.exe']:
        names = {item.replace('\\', '/') for item in CArchiveReader(str(dist / name)).toc}
        if 'mockaize_api/assets/mockaize-favicon.png' not in names:
            raise ValueError(f'{name} não contém o ícone da janela.')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    parser.add_argument('--icon', type=Path, default=Path('src/mockaize_api/assets/mockaize.ico'))
    args = parser.parse_args()
    try:
        result = verify_build(args.dist, args.icon)
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
            stream.write('\nÍcone MockAíZé, arquitetura x64, elevação e payload conferidos.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
