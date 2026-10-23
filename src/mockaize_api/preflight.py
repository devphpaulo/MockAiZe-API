"""Verificações preliminares sob a identidade do processo atual.

Compatibilidade do schema do estúdio será validada pelo leitor COD-02.
"""

from contextlib import closing
import os
import socket
import sqlite3
import tempfile

from .config import ApiConfig


class PreflightError(RuntimeError):
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


def _check_database(config: ApiConfig) -> None:
    try:
        if not config.database_path.is_file():
            raise OSError
        uri = config.database_path.resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as connection:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
    except (OSError, sqlite3.Error):
        raise PreflightError('databasePath', 'O banco SQLite não está acessível para leitura.') from None


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
    _check_database(config)
    _check_directories(config)
    _check_port(config)
