"""Estado SQLite exclusivo da API: contador e replay durável por 24 horas."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import time

from .errors import ApiError


class State:
    def __init__(self, path: Path, retention_seconds: int = 86400):
        self.path, self.retention_seconds = path, retention_seconds
        with self.connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Versão do estado da API incompatível.')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS sequences(file_id TEXT PRIMARY KEY, next_index INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS replays(operation TEXT NOT NULL, key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, created REAL NOT NULL, status INTEGER,
                    headers TEXT, body BLOB, PRIMARY KEY(operation,key));
                CREATE INDEX IF NOT EXISTS replay_expiration ON replays(created);
                PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        try:
            with closing(sqlite3.connect(self.path, timeout=5)) as connection:
                with connection:
                    yield connection
        except sqlite3.Error:
            raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Estado da API indisponível.') from None

    def next_index(self, file_id: str) -> int:
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('INSERT OR IGNORE INTO sequences VALUES (?,0)', (file_id,))
            value = connection.execute('SELECT next_index FROM sequences WHERE file_id=?', (file_id,)).fetchone()[0]
            connection.execute('UPDATE sequences SET next_index=next_index+1 WHERE file_id=?', (file_id,))
            return value

    def begin(self, operation: str, key: str, fingerprint: str) -> dict | None:
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM replays WHERE status IS NOT NULL AND created<?', (time.time() - self.retention_seconds,))
            row = connection.execute('SELECT fingerprint,status,headers,body FROM replays WHERE operation=? AND key=?',
                                     (operation, key)).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise ApiError(409, 'IDEMPOTENCY_CONFLICT', 'A chave já foi usada com outro corpo.')
                if row[1] is None:
                    raise ApiError(409, 'IDEMPOTENCY_IN_PROGRESS', 'Execução em andamento ou interrompida. Verifique os resultados antes de usar outra chave.')
                return {'status': row[1], 'headers': json.loads(row[2]), 'body': bytes(row[3])}
            connection.execute('INSERT INTO replays(operation,key,fingerprint,created) VALUES (?,?,?,?)',
                               (operation, key, fingerprint, time.time()))
            return None

    def complete(self, operation: str, key: str, response: dict) -> None:
        with self.connect() as connection:
            connection.execute('UPDATE replays SET status=?,headers=?,body=? WHERE operation=? AND key=?',
                               (response['status'], json.dumps(response['headers']), response['body'], operation, key))

    def cancel(self, operation: str, key: str) -> None:
        """Somente antes de iniciar a geração; permite retry após lotação."""
        with self.connect() as connection:
            connection.execute('DELETE FROM replays WHERE operation=? AND key=? AND status IS NULL', (operation, key))
