"""Configuração operacional sem segredos, aplicada somente no início."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile

MAX_CONFIG_BYTES = 65_536
PATH_FIELDS = {
    'databasePath': 'database_path', 'inputDirectory': 'input_directory',
    'outputDirectory': 'output_directory', 'logsDirectory': 'logs_directory',
}
FIELD_NAMES = {**PATH_FIELDS, 'port': 'port', 'host': 'host', 'firewallAccess': 'firewall_access'}


class ConfigurationError(ValueError):
    """Diagnóstico seguro: nunca inclui valores fornecidos pelo usuário."""

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


@dataclass(frozen=True)
class ApiConfig:
    database_path: Path
    input_directory: Path
    output_directory: Path
    logs_directory: Path
    port: int
    host: str
    firewall_access: str

    @classmethod
    def from_mapping(cls, values: object) -> 'ApiConfig':
        if not isinstance(values, dict) or set(values) != set(FIELD_NAMES):
            raise ConfigurationError('config', 'Informe exatamente os sete campos operacionais documentados.')
        paths = {attr: _absolute_path(values[key], key) for key, attr in PATH_FIELDS.items()}
        port = values['port']
        if type(port) is not int or not 1 <= port <= 65535:
            raise ConfigurationError('port', 'A porta deve ser um inteiro entre 1 e 65535.')
        pair = (values['host'], values['firewallAccess'])
        if pair not in [('127.0.0.1', 'N'), ('0.0.0.0', 'Y')]:
            raise ConfigurationError('host', 'Use 127.0.0.1 com N ou 0.0.0.0 com Y.')
        if paths['output_directory'].resolve() == paths['logs_directory'].resolve():
            raise ConfigurationError('logsDirectory', 'Saída e logs devem usar diretórios distintos.')
        return cls(**paths, port=port, host=values['host'], firewall_access=values['firewallAccess'])

    def to_mapping(self) -> dict:
        attributes = asdict(self)
        return {key: str(attributes[attr]) if key in PATH_FIELDS else attributes[attr]
                for key, attr in FIELD_NAMES.items()}


def _absolute_path(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ConfigurationError(field, 'Informe um caminho absoluto válido.')
    path = Path(value)
    if not path.is_absolute():
        raise ConfigurationError(field, 'Informe um caminho absoluto válido.')
    return path


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError('config', 'O JSON contém campos repetidos.')
        result[key] = value
    return result


def load_config(path: Path) -> ApiConfig:
    try:
        with path.open('rb') as source:
            content = source.read(MAX_CONFIG_BYTES + 1)
        if len(content) > MAX_CONFIG_BYTES:
            raise ConfigurationError('config', 'A configuração excede 64 KiB.')
        values = json.loads(content.decode('utf-8-sig'), object_pairs_hook=_unique_object)
        return ApiConfig.from_mapping(values)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, RuntimeError, TypeError):
        raise ConfigurationError('config', 'Não foi possível ler uma configuração JSON válida.') from None


def save_config(path: Path, config: ApiConfig) -> None:
    """Troca atômica no mesmo diretório. O chamador deve manter o serviço parado."""
    temporary = None
    try:
        validated = ApiConfig.from_mapping(config.to_mapping())
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.config-', suffix='.tmp', delete=False) as target:
            temporary = Path(target.name)
            json.dump(validated.to_mapping(), target, ensure_ascii=False, indent=2)
            target.write('\n')
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    except OSError:
        raise ConfigurationError('config', 'Não foi possível salvar a configuração.') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
