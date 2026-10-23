"""Limites operacionais ajustáveis fora do config.json de sete campos."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .errors import ApiError


@dataclass(frozen=True)
class Policy:
    requests_per_second: int = 5
    generation_timeout_seconds: int = 60
    generation_concurrency: int = 2
    maximum_connections: int = 16
    idempotency_retention_seconds: int = 86400
    logs_retention_days: int = 30

    @classmethod
    def load(cls, config_path: Path):
        path = config_path.parent / 'policy.json'
        if not path.exists():
            return cls()
        try:
            if path.stat().st_size > 65536:
                raise ValueError
            data = json.loads(path.read_text(encoding='utf-8'))
            defaults = asdict(cls())
            if not isinstance(data, dict) or set(data) - set(defaults):
                raise ValueError
            bounds = {'requests_per_second': (1, 1000), 'generation_timeout_seconds': (1, 300),
                      'generation_concurrency': (1, 8), 'maximum_connections': (2, 128),
                      'idempotency_retention_seconds': (60, 604800), 'logs_retention_days': (1, 3650)}
            for key, value in data.items():
                low, high = bounds[key]
                if type(value) is not int or not low <= value <= high:
                    raise ValueError
            return cls(**data)
        except (OSError, ValueError, TypeError):
            raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Política operacional inválida.') from None
