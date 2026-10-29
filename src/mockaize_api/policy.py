"""Controles operacionais legados e política única resolvida no startup."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .errors import ApiError
from .config import ApiConfig, _unique_object, validate_cleanup_paths


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
            data = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object)
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

    def resolve(self, config: ApiConfig, *, config_path: Path | None = None,
                protected_paths: tuple[Path, ...] = ()) -> 'ResolvedPolicy':
        """Resolve limits and retention once, without writing or scheduling cleanup.

        Explicit cleanup.logs (including disabled) overrides logs_retention_days.
        config_path protects the configuration and its operational sibling files;
        the caller supplies installed binary directories through protected_paths.
        """
        if config_path is not None:
            protected_paths = (*protected_paths, config_path, config_path.parent / 'credentials.json',
                               config_path.parent / 'api-state.sqlite3', config_path.parent / 'policy.json')
        validate_cleanup_paths(config, protected_paths)
        cleanup = config.cleanup
        logs_days = self.logs_retention_days if cleanup.logs is None else cleanup.logs.days
        return ResolvedPolicy(**asdict(self), input_xml_bytes=config.limits.input_xml.resolve(2000000),
                              record_count=config.limits.records.resolve(500),
                              cleanup_inputs_days=cleanup.inputs.days,
                              cleanup_outputs_days=cleanup.outputs.days, cleanup_logs_days=logs_days)


@dataclass(frozen=True)
class ResolvedPolicy(Policy):
    """Pickle/JSON-compatible scalar values passed to generation and startup workers.

    None means disabled. logs_retention_days is only the legacy migration source;
    cleanup_logs_days is the effective retention, with no second cleanup routine.
    """
    input_xml_bytes: int | None = 2000000
    record_count: int | None = 500
    cleanup_inputs_days: int | None = None
    cleanup_outputs_days: int | None = None
    cleanup_logs_days: int | None = 30

    def to_mapping(self) -> dict:
        return asdict(self)
