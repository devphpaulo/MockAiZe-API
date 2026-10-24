"""Private INI bridge used by the native Windows setup and maintenance tools.

This is a local administrator CLI, never an HTTP endpoint. Secrets are returned
only in the caller's private result file; no operation writes them to stdout.
"""
from __future__ import annotations

import argparse
import configparser
import os
from pathlib import Path
import sys
import tempfile

from .catalog import Catalog
from .config import ApiConfig, ConfigurationError, FIELD_NAMES, load_config
from .errors import ApiError
from .preflight import PreflightError, check_environment
from .uninstall import UninstallSession, checked_directory, discover_uninstall_target
from .windows_ops import (SERVICE_EXE, Installation, Installer, WindowsDriver,
                          _is_mapped_network_drive, _is_network_path,
                          discover_installation, validate_origins, wait_health)


OPERATIONS = ('inspect', 'validate', 'stop', 'start', 'restart', 'install',
              'configure', 'detach', 'cleanup')
MAX_REQUEST_BYTES = 131_072


class MaintenanceError(ValueError):
    """A fixed, user-facing diagnostic which contains no caller-controlled data."""


def read_request(path: Path) -> configparser.SectionProxy:
    if not path.is_absolute():
        raise MaintenanceError('O pedido deve usar um caminho absoluto.')
    with path.open('rb') as stream:
        raw = stream.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        raise MaintenanceError('O pedido de manutenção excede o tamanho permitido.')
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(raw.decode('utf-16'))
    if 'setup' not in parser:
        raise MaintenanceError('O pedido de manutenção não contém a seção setup.')
    return parser['setup']


def write_result(path: Path, values: dict) -> None:
    """Publish a complete UTF-16/BOM reply with no transient partial INI file."""
    if not path.is_absolute():
        raise MaintenanceError('O resultado deve usar um caminho absoluto.')
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser['result'] = {key: str(value) for key, value in values.items()}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-16', dir=path.parent,
                                         prefix='.maintenance-', suffix='.ini',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            parser.write(stream, space_around_delimiters=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _absolute(value: str) -> Path:
    if not value or '\x00' in value or '\n' in value or '\r' in value:
        raise MaintenanceError('Informe um caminho absoluto válido.')
    path = Path(value)
    if not path.is_absolute():
        raise MaintenanceError('Informe um caminho absoluto válido.')
    return path.resolve()


def _canonical(installation: Installation) -> Installation:
    return Installation(_absolute(str(installation.directory)),
                        _absolute(str(installation.config_path)),
                        validate_origins(installation.origins))


def _discover(request) -> tuple[Installation | None, bool]:
    """Only the registry or a validated product receipt can identify an install."""
    registered = discover_installation()
    if registered is not None:
        return _canonical(registered), True
    installation = discover_uninstall_target(Path(sys.executable))
    if installation is None and request.get('installDir', ''):
        # Setup runs its helper from a temporary payload. The request can locate
        # an old receipt but cannot authorize a deletion without that receipt.
        directory = _absolute(request['installDir'])
        installation = discover_uninstall_target(directory / SERVICE_EXE)
    return (_canonical(installation), False) if installation else (None, False)


def _match_target(request, installation: Installation) -> None:
    for name, expected in [('installDir', installation.directory),
                           ('configPath', installation.config_path)]:
        if request.get(name, '') and _absolute(request[name]) != expected:
            raise MaintenanceError('O pedido não corresponde à instalação localizada. Reabra o assistente.')


def _configuration(request, installation: Installation | None) -> ApiConfig:
    values = {}
    if installation is not None:
        try:
            values.update(load_config(installation.config_path).to_mapping())
        except ConfigurationError:
            pass  # An explicit repair may replace an unreadable configuration.
    for name in FIELD_NAMES:
        if name in request:
            values[name] = request[name]
    try:
        values['port'] = int(values['port'])
    except (ValueError, KeyError, TypeError):
        raise MaintenanceError('A porta deve ser um inteiro entre 1 e 65535.') from None
    config = ApiConfig.from_mapping(values)
    mapping = config.to_mapping()
    for name in ('databasePath', 'inputDirectory', 'outputDirectory', 'logsDirectory'):
        path = _absolute(mapping[name])
        if _is_mapped_network_drive(path):
            raise MaintenanceError('Use o caminho UNC completo \\\\servidor\\compartilhamento; unidades de rede mapeadas não ficam disponíveis para o serviço Windows.')
        mapping[name] = str(path)
    config_path = request.get('configPath', '')
    if config_path and _is_mapped_network_drive(_absolute(config_path).parent):
        raise MaintenanceError('Use um caminho UNC completo para a configuração; unidades de rede mapeadas não ficam disponíveis para o serviço Windows.')
    return ApiConfig.from_mapping(mapping)


def _snapshot(installation: Installation | None, driver, message='Operação concluída.') -> dict:
    result = {'ok': '1', 'message': message, 'state': driver.status(),
              'restartRequired': '0', 'folderCount': '0'}
    if installation is None:
        result['state'] = 'absent'
        return result
    result.update(installDir=str(installation.directory), configPath=str(installation.config_path),
                  origins=installation.origins, configValid='0')
    try:
        config = load_config(installation.config_path)
    except ConfigurationError:
        return result
    result.update(config.to_mapping())
    result['configValid'] = '1'
    return result


def _folders(result: dict, session: UninstallSession) -> None:
    result['folderCount'] = str(len(session.folders))
    result.update({f'folder{index}': str(path) for index, path in enumerate(session.folders)})


def _prepare(config: ApiConfig) -> None:
    Catalog(config.database_path).check()
    for directory in (config.input_directory, config.output_directory, config.logs_directory):
        directory.mkdir(parents=True, exist_ok=True)
    check_environment(config)


def execute(operation: str, request, driver=None) -> dict:
    """Perform one bounded action. Callers may inject a driver for isolated tests."""
    if operation not in OPERATIONS:
        raise MaintenanceError('Operação de manutenção desconhecida.')
    driver = driver or WindowsDriver()
    installation, registered = _discover(request)
    if operation == 'inspect':
        return _snapshot(installation, driver)
    if installation is not None:
        _match_target(request, installation)
    if operation in ('start', 'restart', 'stop', 'configure') and not registered:
        raise MaintenanceError('A instalação não está registrada. Repare-a usando o instalador.')
    if operation == 'stop':
        driver.stop()
        Installer(installation, driver).require_stopped()
        return _snapshot(installation, driver, 'Serviço parado.')
    if operation in ('start', 'restart'):
        config = load_config(installation.config_path)
        if operation == 'restart':
            driver.stop()
            Installer(installation, driver).require_stopped()
        driver.start()
        wait_health(config)
        return _snapshot(installation, driver, 'Serviço ativo e respondendo na porta configurada.')
    if operation in ('detach', 'cleanup'):
        if installation is None:
            raise MaintenanceError('Nenhuma instalação ou recibo válido foi localizado. Nenhum arquivo foi removido.')
        session = UninstallSession(installation, driver)
        result = _snapshot(installation, driver)
        _folders(result, session)
        if operation == 'detach':
            session.detach()
            result.update(state=driver.status(), message='Serviço removido da listagem do Windows.')
            return result
        # A second helper process cannot inherit an in-memory detach flag. It
        # must observe SCM absence, then reconstruct the same protected allowlist.
        if driver.status() != 'absent':
            raise MaintenanceError('Remova primeiro o serviço. Nenhum arquivo foi limpo.')
        try:
            count = int(request.get('folderCount', '0'))
            if not 0 <= count <= len(session.folders):
                raise ValueError
            if request.get('cleanBinaries', '0') not in ('0', '1'):
                raise ValueError
            folders = [_absolute(request[f'folder{index}']) for index in range(count)]
        except (ValueError, KeyError):
            raise MaintenanceError('A seleção de limpeza é inválida. Nenhum arquivo foi removido.') from None
        session.detached = True
        removed = session.cleanup(request.get('cleanBinaries', '0') == '1', folders)
        result.update(state='absent', restartRequired='1' if removed['restartRequired'] else '0',
                      message='OK. Desinstalação concluída conforme as opções selecionadas.')
        return result
    config = _configuration(request, installation)
    origins = validate_origins(request.get('origins', installation.origins if installation else 'LocalSubnet'))
    if operation == 'validate':
        if driver.status() not in ('absent', 'stopped'):
            raise MaintenanceError('Pare explicitamente o serviço antes de verificar a porta e os diretórios.')
        _prepare(config)
        result = _snapshot(installation, driver, 'Banco, diretórios, porta e acesso validados.')
        result.update(config.to_mapping(), origins=origins)
        return result
    if operation == 'configure':
        Catalog(config.database_path).check()
        Installer(installation, driver).change_config(config, origins)
        return _snapshot(Installation(installation.directory, installation.config_path, origins), driver,
                         'Configuração salva; serviço reiniciado e saudável.')
    # Existing valid configuration is intentionally preserved by Installer.install.
    # Repair gets the entered replacement only when the saved configuration is invalid.
    if installation is None:
        directory = _absolute(request.get('installDir', ''))
        if _is_network_path(directory):
            raise MaintenanceError('Os binários do serviço precisam ficar em uma pasta local, como Program Files.')
        directory = checked_directory(directory, config.database_path)
        if directory.exists() and any(directory.iterdir()):
            raise MaintenanceError('Escolha uma pasta vazia dedicada ao MockAiZe API. Os arquivos existentes foram preservados.')
        installation = Installation(directory, _absolute(request.get('configPath', '')), origins)
    else:
        installation = Installation(installation.directory, installation.config_path, origins)
        checked_directory(installation.directory, config.database_path)
    payload = _absolute(request.get('payloadDirectory', ''))
    if payload == installation.directory or payload.is_relative_to(installation.directory):
        raise MaintenanceError('O pacote temporário deve ficar fora da pasta de instalação.')
    try:
        effective = load_config(installation.config_path)
    except ConfigurationError:
        effective = config
    Catalog(effective.database_path).check()
    token = Installer(installation, driver).install(payload, config)
    result = _snapshot(installation, driver, 'API instalada; serviço ativo e saudável.')
    if token is not None:
        result['apiKey'] = token
    return result


def _safe_message(error: Exception) -> str:
    if isinstance(error, (MaintenanceError, ConfigurationError, PreflightError, ApiError)):
        return str(error).replace('\r', ' ').replace('\n', ' ')
    return 'Não foi possível concluir a operação. Verifique o estado do serviço, as permissões e os logs da instalação.'


def main(arguments=None) -> int:
    parser = argparse.ArgumentParser(description='Manutenção local do MockAiZe API')
    parser.add_argument('--maintenance', choices=OPERATIONS, required=True)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    options = parser.parse_args(arguments)
    initialized = False
    try:
        if not options.request.is_absolute() or not options.result.is_absolute():
            raise MaintenanceError('Pedido e resultado devem usar caminhos absolutos.')
        if options.request.resolve() == options.result.resolve():
            raise MaintenanceError('Pedido e resultado devem usar arquivos diferentes.')
        request = read_request(options.request)
        if os.name == 'nt':
            import pythoncom
            pythoncom.CoInitialize()
            initialized = True
        result = execute(options.maintenance, request)
    except Exception as error:
        result = {'ok': '0', 'message': _safe_message(error), 'restartRequired': '0', 'errorType': type(error).__name__}
    finally:
        if initialized:
            pythoncom.CoUninitialize()
    try:
        write_result(options.result, result)
    except (OSError, ValueError):
        return 2
    return 0 if result['ok'] == '1' else 1


if __name__ == '__main__':
    raise SystemExit(main())
