"""Inspeção estática de um artefato existente: nunca inicia os executáveis."""
import argparse
import hashlib
import json
from pathlib import Path


def file_hashes(path):
    hashes = {}
    for algorithm in ('md5', 'sha256'):
        with path.open('rb') as stream:
            hashes[algorithm] = hashlib.file_digest(stream, algorithm).hexdigest()
    return hashes


def require_identity(actual, expected):
    for algorithm in ('md5', 'sha256'):
        if actual[algorithm].lower() != expected[algorithm].lower():
            raise ValueError(f'{algorithm.upper()} diferente da amostra esperada; identidade não confirmada.')


def inspect_executable(path):
    import pefile
    from PyInstaller.archive.readers import CArchiveReader
    hashes = file_hashes(path)
    with pefile.PE(str(path), fast_load=True) as pe:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        imports = [entry.dll.decode('ascii', errors='replace')
                   for entry in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])]
        machine = hex(pe.FILE_HEADER.Machine)
    archive = CArchiveReader(str(path))
    largest = sorted(archive.toc.items(), key=lambda item: item[1][2], reverse=True)[:16]
    embedded = []
    for name, entry in archive.toc.items():
        if name.lower().endswith('.exe'):
            content = archive.extract(name)
            embedded.append({'name': name, 'sizeBytes': len(content),
                             'sha256': hashlib.sha256(content).hexdigest()})
    return {'fileName': path.name, 'sizeBytes': path.stat().st_size, **hashes,
            'machine': machine, 'importedLibraries': imports,
            'archiveEntries': len(archive.toc),
            'archiveUncompressedBytes': sum(entry[2] for entry in archive.toc.values()),
            'largestEntries': [{'name': name, 'compressedBytes': entry[1],
                                'uncompressedBytes': entry[2]} for name, entry in largest],
            'embeddedExecutables': embedded}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--expected-md5', required=True)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    setup = args.directory / 'MockAiZe-API-Setup.exe'
    expected = {'md5': args.expected_md5, 'sha256': args.expected_sha256}
    actual = file_hashes(setup)
    require_identity(actual, expected)
    result = {'identity': 'matches-reported-md5-and-build-sha256',
              'executed': False, 'malwareVerdict': 'not-determined-by-static-inspection',
              'files': [inspect_executable(path) for path in sorted(args.directory.glob('*.exe'))]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'identity': result['identity'], 'executed': False,
                      'files': [{key: entry[key] for key in ('fileName', 'sizeBytes', 'md5', 'sha256')}
                                for entry in result['files']]}, indent=2))


if __name__ == '__main__':
    main()
