"""Start frozen GUI diagnostics in an unrelated directory with no developer DLL paths."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, action='append', required=True)
    args = parser.parse_args()
    environment = {name: value for name, value in os.environ.items()
                   if name.upper() not in {'PATH', 'PYTHONPATH', 'PYTHONHOME'}
                   and not name.upper().startswith(('QT_', 'QML'))}
    windows = Path(os.environ['SystemRoot'])
    environment['PATH'] = os.pathsep.join(str(path) for path in (windows / 'System32', windows))
    for argument in args.binary:
        binary = argument.resolve(strict=True)
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'ui-report.json'
            try:
                process = subprocess.run([str(binary), '--diagnose-ui', str(report)], cwd=folder,
                                         env=environment, capture_output=True, text=True, timeout=60,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except OSError as error:
                raise RuntimeError('Diagnóstico gráfico requer runner Windows com elevação; '
                                   'nenhum serviço será instalado.') from error
            result = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
            if process.returncode != 0 or result.get('status') != 'passed' or result.get('platform') != 'windows':
                raise RuntimeError(f'{binary.name}: Qt compilado não iniciou. {result} {process.stderr}')
            print(json.dumps({'binary': binary.name, 'frozenUiSmoke': 'passed', **result}))


if __name__ == '__main__':
    main()
