"""JSON Lines diário sanitizado; a retenção pertence à rodada de startup."""
from datetime import datetime
import json
from pathlib import Path
import threading

from .errors import ApiError


class RequestLog:
    def __init__(self, directory: Path, retention_days: int = 30):
        self.directory = directory
        self.retention_days = retention_days
        self.lock = threading.Lock()

    def write(self, **values) -> None:
        allowed = {'requestId', 'method', 'route', 'status', 'durationMs', 'code', 'fileId',
                   'sourceRevision', 'composition', 'files', 'residue',
                   'responseTraceId', 'replayOfTraceId', 'event', 'authenticated', 'authMethod',
                   'cleanupScope', 'scanned', 'deleted', 'skipped', 'failures', 'attempts', 'result'}
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
        except OSError:
            raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Log operacional indisponível.') from None
