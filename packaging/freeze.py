"""Compile with a bounded native search path; reject foreign toolchain DLLs."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys


def isolated_environment(original, executable, base_prefix, windows):
    removed = {'PATH', 'PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QML2_IMPORT_PATH',
               'QML_IMPORT_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_PLATFORM'}
    result = {name: value for name, value in original.items() if name.upper() not in removed}
    paths = [Path(executable).resolve().parent, Path(base_prefix).resolve(),
             Path(base_prefix).resolve() / 'DLLs', Path(windows).resolve() / 'System32',
             Path(windows).resolve()]
    result['PATH'] = os.pathsep.join(str(path) for path in dict.fromkeys(paths))
    return result


def validate_native_sources(entries, allowed):
    roots = [Path(path).resolve() for path in allowed]
    for destination, source, kind in entries:
        if kind == 'BINARY' and not any(Path(source).resolve().is_relative_to(root) for root in roots):
            raise ValueError(f'DLL/binário de ferramenta externa recusado: {destination} ({source}).')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('spec', type=Path)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('O build de distribuição requer Windows.')
    root = Path(__file__).resolve().parents[1]
    spec = args.spec.resolve(strict=True)
    environment = isolated_environment(os.environ, sys.executable, sys.base_prefix, os.environ['SystemRoot'])
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', str(spec)],
                   cwd=root, env=environment, check=True)
    analysis = ast.literal_eval((root / 'build' / spec.stem / 'Analysis-00.toc').read_text(encoding='utf-8'))
    entries = [entry for value in analysis if isinstance(value, list)
               for entry in value if isinstance(entry, tuple) and len(entry) == 3 and entry[-1] == 'BINARY']
    if not entries:
        raise RuntimeError('O inventário de bibliotecas nativas do build não foi encontrado.')
    validate_native_sources(entries, [root, sys.prefix, sys.base_prefix, os.environ['SystemRoot']])
    print(json.dumps({'nativeSources': 'verified', 'spec': spec.name, 'binaries': len(entries)}))


if __name__ == '__main__':
    main()
