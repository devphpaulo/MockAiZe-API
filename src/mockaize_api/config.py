"""Configuração operacional sem segredos, aplicada somente no início."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile

MAX_CONFIG_BYTES = 65_536
PATH_FIELDS = {
    'databasePath': 'database_path', 'inputDirectory': 'input_directory',
    'outputDirectory': 'output_directory', 'logsDirectory': 'logs_directory',
}
FIELD_NAMES = {**PATH_FIELDS, 'port': 'port', 'host': 'host', 'firewallAccess': 'firewall_access'}
OPTIONAL_FIELDS = {'presetsDirectory', 'authentication', 'limits', 'cleanup'}


class ConfigurationError(ValueError):
    """Diagnóstico seguro: nunca inclui valores fornecidos pelo usuário."""

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


def _object(value: object, allowed: set[str], field_name: str) -> dict:
    if not isinstance(value, dict) or set(value) - allowed:
        raise ConfigurationError(field_name, 'Informe apenas os campos documentados.')
    return value


@dataclass(frozen=True)
class Limit:
    mode: str = 'default'
    value: int | None = None

    @classmethod
    def from_mapping(cls, value: object, unit: str, field_name: str) -> 'Limit':
        value = _object(value, {'mode', unit}, field_name)
        mode = value.get('mode')
        if mode not in ('default', 'custom', 'disabled'):
            raise ConfigurationError(field_name, 'Use default, custom ou disabled.')
        if mode == 'custom':
            amount = value.get(unit)
            if type(amount) is not int or amount < 1:
                raise ConfigurationError(field_name, 'O limite personalizado deve ser um inteiro positivo.')
            return cls(mode, amount)
        if unit in value:
            raise ConfigurationError(field_name, 'Informe um valor somente no modo custom.')
        return cls(mode)

    def resolve(self, default: int) -> int | None:
        return {'default': default, 'custom': self.value, 'disabled': None}[self.mode]

    def to_mapping(self, unit: str) -> dict:
        return {'mode': self.mode, **({unit: self.value} if self.mode == 'custom' else {})}


@dataclass(frozen=True)
class Limits:
    input_xml: Limit = field(default_factory=Limit)
    records: Limit = field(default_factory=Limit)

    @classmethod
    def from_mapping(cls, value: object) -> 'Limits':
        value = _object(value, {'inputXml', 'records'}, 'limits')
        return cls(Limit.from_mapping(value.get('inputXml', {'mode': 'default'}), 'bytes', 'limits.inputXml'),
                   Limit.from_mapping(value.get('records', {'mode': 'default'}), 'count', 'limits.records'))

    def to_mapping(self) -> dict:
        return {'inputXml': self.input_xml.to_mapping('bytes'), 'records': self.records.to_mapping('count')}


@dataclass(frozen=True)
class Authentication:
    required: bool = True

    @classmethod
    def from_mapping(cls, value: object) -> 'Authentication':
        value = _object(value, {'required'}, 'authentication')
        required = value.get('required', True)
        if type(required) is not bool:
            raise ConfigurationError('authentication.required', 'Informe true ou false.')
        return cls(required)


@dataclass(frozen=True)
class CleanupRule:
    mode: str = 'disabled'
    days: int | None = None

    @classmethod
    def from_mapping(cls, value: object, field_name: str) -> 'CleanupRule':
        value = _object(value, {'mode', 'days'}, field_name)
        if value.get('mode') == 'disabled' and 'days' not in value:
            return cls()
        if value.get('mode') == 'age' and type(value.get('days')) is int and value['days'] >= 1:
            return cls('age', value['days'])
        raise ConfigurationError(field_name, 'Use disabled ou age com days inteiro positivo.')

    def to_mapping(self) -> dict:
        return {'mode': self.mode, **({'days': self.days} if self.mode == 'age' else {})}


@dataclass(frozen=True)
class Cleanup:
    inputs: CleanupRule = field(default_factory=CleanupRule)
    outputs: CleanupRule = field(default_factory=CleanupRule)
    # None preserves omission: policy.json supplies the migration default for logs.
    logs: CleanupRule | None = None

    @classmethod
    def from_mapping(cls, value: object) -> 'Cleanup':
        value = _object(value, {'inputs', 'outputs', 'logs'}, 'cleanup')
        return cls(**{key: CleanupRule.from_mapping(rule, 'cleanup.' + key)
                      for key, rule in value.items()})

    def to_mapping(self) -> dict:
        result = {'inputs': self.inputs.to_mapping(), 'outputs': self.outputs.to_mapping()}
        if self.logs is not None:
            result['logs'] = self.logs.to_mapping()
        return result


@dataclass(frozen=True)
class ApiConfig:
    database_path: Path
    input_directory: Path
    output_directory: Path
    logs_directory: Path
    port: int
    host: str
    firewall_access: str
    presets_directory: Path | None = None
    authentication: Authentication = field(default_factory=Authentication)
    limits: Limits = field(default_factory=Limits)
    cleanup: Cleanup = field(default_factory=Cleanup)

    def __post_init__(self):
        if self.presets_directory is None:
            object.__setattr__(self, 'presets_directory', self.database_path.parent / 'Presets')

    @classmethod
    def from_mapping(cls, values: object) -> 'ApiConfig':
        if (not isinstance(values, dict) or set(FIELD_NAMES) - set(values)
                or set(values) - set(FIELD_NAMES) - OPTIONAL_FIELDS):
            raise ConfigurationError('config', 'Informe os sete campos operacionais e somente opções documentadas.')
        paths = {attr: _absolute_path(values[key], key) for key, attr in PATH_FIELDS.items()}
        port = values['port']
        if type(port) is not int or not 1 <= port <= 65535:
            raise ConfigurationError('port', 'A porta deve ser um inteiro entre 1 e 65535.')
        pair = (values['host'], values['firewallAccess'])
        if pair not in [('127.0.0.1', 'N'), ('0.0.0.0', 'Y')]:
            raise ConfigurationError('host', 'Use 127.0.0.1 com N ou 0.0.0.0 com Y.')
        if paths['output_directory'].resolve() == paths['logs_directory'].resolve():
            raise ConfigurationError('logsDirectory', 'Saída e logs devem usar diretórios distintos.')
        config = cls(**paths, port=port, host=values['host'], firewall_access=values['firewallAccess'],
                     presets_directory=_absolute_path(values['presetsDirectory'], 'presetsDirectory')
                     if 'presetsDirectory' in values else None,
                     authentication=Authentication.from_mapping(values.get('authentication', {})),
                     limits=Limits.from_mapping(values.get('limits', {})),
                     cleanup=Cleanup.from_mapping(values.get('cleanup', {})))
        validate_cleanup_paths(config)
        return config

    def to_mapping(self) -> dict:
        result = {key: str(getattr(self, attr)) if key in PATH_FIELDS else getattr(self, attr)
                  for key, attr in FIELD_NAMES.items()}
        result.update(presetsDirectory=str(self.presets_directory),
                      authentication={'required': self.authentication.required},
                      limits=self.limits.to_mapping(), cleanup=self.cleanup.to_mapping())
        return result


def validate_cleanup_paths(config: ApiConfig, protected_paths: tuple[Path, ...] = ()) -> None:
    """Validate canonical roots; callers add config/state/credentials and binary locations.

    No filesystem mutation is performed. The worker must revalidate before deletion.
    """
    roots = {'inputs': config.input_directory.resolve(), 'outputs': config.output_directory.resolve(),
             'logs': config.logs_directory.resolve()}
    protected = [config.database_path.resolve(), config.presets_directory.resolve(),
                 *(Path(path).resolve() for path in protected_paths)]
    home = Path.home().resolve()
    profile_paths = _windows_profile_paths() if any(
        getattr(config.cleanup, key) is None or getattr(config.cleanup, key).mode != 'disabled'
        for key in roots) else set()
    for key, root in roots.items():
        rule = getattr(config.cleanup, key)
        if rule is not None and rule.mode == 'disabled':
            continue
        if (root == Path(root.anchor) or home.is_relative_to(root)
                or any(profile.is_relative_to(root) for profile in profile_paths)):
            raise ConfigurationError('cleanup.' + key, 'A limpeza exige um diretório específico da aplicação.')
        if any(path.is_relative_to(root) or root.is_relative_to(path)
               for other, path in roots.items() if other != key):
            raise ConfigurationError('cleanup.' + key, 'As raízes de limpeza não podem ser iguais ou sobrepostas.')
        if any(path.is_relative_to(root) or root.is_relative_to(path) for path in protected):
            raise ConfigurationError('cleanup.' + key, 'A raiz de limpeza contém arquivos ou diretórios protegidos.')


def _windows_profile_paths() -> set[Path]:
    """Read Windows' registered profile locations, independently of the service account.

    Microsoft documents ProfilesDirectory and ProfileImagePath under ProfileList.
    An unavailable registry must not silently turn an empty profile list into permission to delete.
    """
    if os.name != 'nt':
        return set()
    def profile_path(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError
        expanded = os.path.expandvars(value)
        path = Path(expanded)
        if not path.is_absolute() or re.search(r'%[^%]+%', expanded):
            raise ValueError
        return path.resolve()
    try:
        import winreg
        paths = set()
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList') as profiles:
            directory, _ = winreg.QueryValueEx(profiles, 'ProfilesDirectory')
            paths.add(profile_path(directory))
            count, _, _ = winreg.QueryInfoKey(profiles)
            for index in range(count):
                with winreg.OpenKey(profiles, winreg.EnumKey(profiles, index)) as profile:
                    image, _ = winreg.QueryValueEx(profile, 'ProfileImagePath')
                    paths.add(profile_path(image))
        if not paths or any(not path.is_absolute() for path in paths):
            raise ValueError
        return paths
    except (OSError, ValueError, TypeError):
        raise ConfigurationError('cleanup', 'Não foi possível verificar os diretórios de perfis protegidos.') from None


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
