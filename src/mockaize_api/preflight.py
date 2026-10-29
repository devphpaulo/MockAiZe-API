"""Verificações preliminares sob a identidade do processo atual.

Compatibilidade do schema do estúdio será validada pelo leitor COD-02.
"""

import os
import socket
import tempfile

from .catalog import Catalog
from .config import ApiConfig
from .errors import ApiError


class PreflightError(RuntimeError):
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


def _check_catalog(config: ApiConfig) -> None:
    try:
        Catalog(config.database_path, config.presets_directory).preflight()
    except ApiError:
        raise PreflightError('catalog', 'Não há um catálogo de presets ou banco SQLite acessível.') from None


def _check_directories(config: ApiConfig) -> None:
    for field, directory in [('inputDirectory', config.input_directory),
                             ('outputDirectory', config.output_directory),
                             ('logsDirectory', config.logs_directory)]:
        try:
            if not directory.is_dir():
                raise OSError
            with os.scandir(directory) as entries:
                next(entries, None)
            if field != 'inputDirectory':
                with tempfile.TemporaryFile(dir=directory) as probe:
                    probe.write(b'MockAiZe API preflight')
                    probe.flush()
                    os.fsync(probe.fileno())
        except OSError:
            raise PreflightError(field, 'Diretório ausente ou sem as permissões necessárias.') from None


def _check_port(config: ApiConfig) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((config.host, config.port))
    except OSError:
        raise PreflightError('port', 'A porta não está disponível no endereço configurado.') from None


def check_environment(config: ApiConfig) -> None:
    _check_catalog(config)
    _check_directories(config)
    _check_port(config)
