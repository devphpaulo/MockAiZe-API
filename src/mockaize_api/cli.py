"""Entrada de desenvolvimento; não registra serviço nem abre interface."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .config import ConfigurationError, load_config
from .preflight import PreflightError, check_environment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='MockAíZé API — validação preliminar de ambiente')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--config', type=Path, help='Caminho explícito do config.json')
    parser.add_argument('--check', action='store_true', help='Validar JSON, banco, pastas e porta; sair')
    args = parser.parse_args(argv)
    if not args.check or args.config is None:
        parser.error('Use --config CAMINHO --check. O host HTTP ainda não está implementado.')
    try:
        check_environment(load_config(args.config))
    except (ConfigurationError, PreflightError) as error:
        print(json.dumps({'status': 'error', 'code': 'PREFLIGHT_FAILED',
                          'field': error.field, 'detail': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({'status': 'preflight-passed', 'version': __version__}))
    return 0
