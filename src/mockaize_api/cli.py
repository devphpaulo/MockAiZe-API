"""Entrada de desenvolvimento; não registra serviço nem abre interface."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .config import ConfigurationError, load_config
from .preflight import PreflightError, check_environment
from .errors import ApiError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='MockAíZé API standalone')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--config', type=Path, help='Caminho explícito do config.json')
    operation = parser.add_mutually_exclusive_group(required=False)
    operation.add_argument('--check', action='store_true', help='Validar JSON, banco, pastas e porta; sair')
    operation.add_argument('--serve', action='store_true', help='Executar API em primeiro plano')
    operation.add_argument('--create-key', action='store_true', help='Criar chave e exibir uma única vez')
    operation.add_argument('--rotate-key', action='store_true', help='Substituir chave de acesso e exibir uma única vez')
    args = parser.parse_args(argv)
    if not any([args.check, args.serve, args.create_key, args.rotate_key]) or args.config is None:
        parser.error('Use --config CAMINHO e --check, --serve, --create-key ou --rotate-key.')
    try:
        if args.create_key or args.rotate_key:
            from .security import create_credentials
            load_config(args.config)
            print(create_credentials(args.config, rotate=args.rotate_key))
            return 0
        if args.serve:
            from .runtime import serve
            serve(args.config)
            return 0
        check_environment(load_config(args.config))
    except (ConfigurationError, PreflightError, ApiError, OSError) as error:
        print(json.dumps({'status': 'error', 'code': 'PREFLIGHT_FAILED',
                          'field': getattr(error, 'field', 'service'),
                          'detail': str(error) if not isinstance(error, OSError) else 'Não foi possível iniciar o serviço.'}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({'status': 'preflight-passed', 'version': __version__}))
    return 0
