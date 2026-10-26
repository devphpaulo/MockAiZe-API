"""JSON Lines diário sanitizado; retenção padrão de trinta dias."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import threading

from .errors import ApiError


class RequestLog:
    def __init__(self, directory: Path, retention_days: int = 30):
        self.directory = directory
        self.retention_days = retention_days
        self.lock = threading.Lock()
        self.last_cleanup = None

    def write(self, **values) -> None:
        allowed = {'requestId', 'method', 'route', 'status', 'durationMs', 'code', 'fileId',
                   'sourceRevision', 'composition', 'files', 'residue',
                   'responseTraceId', 'replayOfTraceId'}
        now = datetime.now().astimezone()
        entry = {key: value for key, value in values.items() if key in allowed}
        if 'files' in entry:
            file_fields = {'fileName', 'records', 'sha256', 'sizeBytes', 'sizeDisplay',
                           'returnId', 'returnName', 'collisionRenamed'}
            entry['files'] = [{key: value for key, value in item.items() if key in file_fields}
                              for item in entry['files']]
        entry['timestamp'] = now.isoformat()
        try:
            with self.lock:
                target = self.directory / f'mockaize-api-logs-{now:%d%m%Y}.txt'
                with target.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
                    stream.flush()
                if self.last_cleanup != now.date():
                    self._cleanup(now)
                    self.last_cleanup = now.date()
        except OSError:
            raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Log operacional indisponível.') from None

    def _cleanup(self, now):
        cutoff = now.date() - timedelta(days=self.retention_days)
        for path in self.directory.glob('mockaize-api-logs-????????.txt'):
            try:
                date = datetime.strptime(path.stem.removeprefix('mockaize-api-logs-'), '%d%m%Y').date()
            except ValueError:
                continue
            if date < cutoff:
                path.unlink()
