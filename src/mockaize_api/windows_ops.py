"""Transactional installer orchestration and narrowly scoped Windows operations."""
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

from .config import ApiConfig, ConfigurationError, load_config, save_config
from .policy import Policy
from .windows_service import REGISTRY_KEY, SERVICE_NAME

FIREWALL_RULE = 'MockAiZe API HTTP'
SERVICE_EXE = 'MockAiZeApiService.exe'
CONFIG_EXE = 'MockAiZeApiConfig.exe'
UNINSTALL_EXE = 'MockAiZeApiUninstall.exe'
SERVICE_ACCOUNT = r'NT AUTHORITY\NetworkService'
SERVICE_SID = '*S-1-5-20'  # NetworkService; presents the computer account on SMB.


class ConfigurationRollbackError(RuntimeError):
    """Fixed public diagnostic, retaining the original and rollback failures privately."""
    def __init__(self, original_error, failures):
        self.original_error = original_error
        self.rollback_errors = tuple(failures)
        permissions = any(stage == 'input_permissions' for stage, _ in failures)
        incomplete = any(stage != 'input_permissions' for stage, _ in failures)
        if incomplete:
            message = 'A operação falhou e a restauração ficou incompleta. Verifique a configuração e o serviço.'
        else:
            message = 'A configuração anterior foi restaurada e o reinício do serviço foi solicitado.'
        if permissions:
            message += (' A permissão de exclusão da nova pasta de entradas pode permanecer ativa.'
                        ' Revise essa permissão antes de tentar novamente.')
        super().__init__(message)


def _is_network_path(path: Path) -> bool:
    """Return whether Windows resolves this path through a remote drive/share."""
    value = str(path)
    if value.startswith('\\\\'):
        return True
    if os.name != 'nt' or not path.drive:
        return False
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(path.drive + '\\') == 4


def _is_mapped_network_drive(path: Path) -> bool:
    """Mapped letters belong to the interactive logon and are invisible to SCM services."""
    if os.name != 'nt' or not path.drive or str(path).startswith('\\\\'):
        return False
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(path.drive + '\\') == 4


def _current_user_sid() -> str:
    """Return the installing user's SID for a narrow input-folder grant."""
    import win32api
    import win32con
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return win32security.ConvertSidToStringSid(sid)
    finally:
        win32api.CloseHandle(token)


@dataclass(frozen=True)
class Installation:
    directory: Path
    config_path: Path
    origins: str = 'LocalSubnet'


def validate_operational_policy(installation: Installation, config: ApiConfig) -> None:
    """Reject unsafe effective policies before touching folders, ACLs or SCM."""
    validated = ApiConfig.from_mapping(config.to_mapping())
    Policy.load(installation.config_path).resolve(
        validated, config_path=installation.config_path,
        protected_paths=(installation.directory.resolve(), Path(__file__).resolve().parent,
                         Path(sys.executable).resolve().parent))


def validate_origins(value: str) -> str:
    parts = [part.strip() for part in value.split(',')]
    if not parts or any(not part for part in parts):
        raise ValueError('Informe IPs ou sub-redes confiáveis separados por vírgula.')
    for part in parts:
        if part != 'LocalSubnet':
            network = ipaddress.ip_network(part, strict=False)
            if network.prefixlen == 0:
                raise ValueError('Autorize apenas IPs ou sub-redes específicas.')
    return ','.join(parts)


def wait_health(config: ApiConfig, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    opener = build_opener(ProxyHandler({}))
    while True:
        try:
            with opener.open(f'http://127.0.0.1:{config.port}/health', timeout=2) as response:
                if response.status == 200:
                    status = json.load(response)
                    if isinstance(status, dict) and status.get('status') == 'ok':
                        return
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('O serviço não confirmou saúde na porta salva. Consulte os logs e repare a instalação.')
        time.sleep(0.3)


class Installer:
    def __init__(self, installation: Installation, driver=None, progress=None):
        self.installation = installation
        self.driver = driver or WindowsDriver()
        self.progress = progress or (lambda message: None)

    def require_stopped(self):
        # Always query SCM here, immediately before a binary swap or config write.
        state = self.driver.status()
        if state not in ('absent', 'stopped'):
            raise RuntimeError('O serviço ainda está em execução. Pare-o e verifique novamente.')

    def install(self, payload: Path, config: ApiConfig | None = None) -> str | None:
        target = self.installation.directory
        config_path = self.installation.config_path
        registration_absent = self.driver.status() == 'absent'
        self.require_stopped()
        previous = config_path.exists()
        invalid_config = None
        if previous:
            try:
                config = load_config(config_path)
            except ConfigurationError:
                if config is None:
                    raise
                invalid_config = config_path.read_bytes()
        if config is None:
            raise ValueError('A instalação nova exige configuração.')
        validate_operational_policy(self.installation, config)
        for executable in (SERVICE_EXE, CONFIG_EXE, UNINSTALL_EXE):
            if not (payload / executable).is_file():
                raise RuntimeError('O pacote do instalador está incompleto. Baixe uma versão íntegra.')
        self.progress('Validando banco, diretórios e porta…')
        for directory in (config.input_directory, config.output_directory, config.logs_directory):
            directory.mkdir(parents=True, exist_ok=True)
        from .preflight import check_environment
        check_environment(config)
        origins = validate_origins(self.installation.origins)
        backup = target.with_name(target.name + '.rollback')
        staged = target.with_name(target.name + '.staging')
        if backup.exists() or staged.exists():
            raise RuntimeError('Existe uma cópia de recuperação anterior. Preserve-a e use outro diretório após diagnóstico.')
        token = None
        created_config = False
        created_credentials = False
        swapped = False
        had_target = target.exists()
        try:
            self.progress('Preparando cópia dos binários…')
            shutil.copytree(payload, staged)
            self.require_stopped()
            if had_target:
                target.rename(backup)
            try:
                staged.rename(target)
            except Exception:
                if backup.exists():
                    backup.rename(target)
                raise
            swapped = True
            receipt = {'product': 'MockAiZe API', 'version': 1, 'directory': str(target),
                       'configPath': str(config_path), 'origins': self.installation.origins}
            receipt_path = target / 'installation.json'
            receipt_temporary = target / '.installation.json.tmp'
            receipt_temporary.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
            os.replace(receipt_temporary, receipt_path)
            if not previous or invalid_config is not None:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                if invalid_config is not None:
                    # Explicit repair keeps the original available for diagnosis.
                    with config_path.with_name('config.invalid-backup.json').open('xb') as backup_config:
                        backup_config.write(invalid_config)
                save_config(config_path, config)
                created_config = not previous
            from .security import create_credentials
            if not (config_path.parent / 'credentials.json').exists():
                token = create_credentials(config_path)
                created_credentials = True
            self.progress('Aplicando permissões e registrando início automático…')
            self.driver.configure(self.installation, config)
            self.progress('Iniciando serviço Windows…')
            self.driver.start()
            self.progress(f'Verificando /health na porta {config.port}…')
            wait_health(config)
            self.progress('HTTP 200 · serviço saudável.')
        except Exception:
            if swapped:
                self.progress('Falha: restaurando binários anteriores…')
                # Do not replace files while a failed service is still alive.
                self.driver.stop()
                self.require_stopped()
                # A key shown only after health must not become an inaccessible
                # orphan on failure. Remove only files this attempt created.
                if created_credentials:
                    (config_path.parent / 'credentials.json').unlink(missing_ok=True)
                if created_config:
                    config_path.unlink(missing_ok=True)
                if invalid_config is not None:
                    config_path.write_bytes(invalid_config)
                shutil.rmtree(target)
                if backup.exists():
                    backup.rename(target)
                if registration_absent:
                    self.driver.remove_registration()
            raise
        finally:
            if staged.exists():
                shutil.rmtree(staged)
        if backup.exists():
            shutil.rmtree(backup)
        return token

    def change_config(self, config: ApiConfig, origins: str) -> None:
        validate_operational_policy(self.installation, config)
        old = load_config(self.installation.config_path)
        self.driver.stop()
        self.require_stopped()
        from .preflight import check_environment
        new_inputs_touched = False
        try:
            installation = Installation(self.installation.directory, self.installation.config_path,
                                        validate_origins(origins))
            for directory in (config.input_directory, config.output_directory, config.logs_directory):
                directory.mkdir(parents=True, exist_ok=True)
            check_environment(config)
            if old.input_directory != config.input_directory and old.cleanup.inputs.mode == 'age':
                self.driver.revoke_input_delete(old, self.installation.config_path.parent)
            save_config(installation.config_path, config)
            new_inputs_touched = old.input_directory != config.input_directory and config.cleanup.inputs.mode == 'age'
            self.driver.configure(installation, config)
            self.driver.start()
            wait_health(config)
        except Exception as original_error:
            self.driver.stop()
            self.require_stopped()
            self._restore_configuration(old, config, new_inputs_touched, original_error)
            raise

    def _restore_configuration(self, old, new, new_inputs_touched, original_error):
        failures = []
        if new_inputs_touched:
            try:
                self.driver.revoke_input_delete(new, self.installation.config_path.parent)
            except Exception as error:
                failures.append(('input_permissions', error))
        steps = (
            ('configuration', lambda: save_config(self.installation.config_path, old)),
            ('service_configuration', lambda: self.driver.configure(self.installation, old)),
        )
        for stage, restore in steps:
            try:
                restore()
            except Exception as error:
                failures.append((stage, error))
        # Never start with the new JSON or an uncertain service configuration.
        # A residual permission failure alone does not prevent the old service
        # from restarting, but failed restoration must leave it stopped.
        if not any(stage != 'input_permissions' for stage, _ in failures):
            try:
                self.driver.start()
            except Exception as error:
                failures.append(('service_start', error))
        if failures:
            raise ConfigurationRollbackError(original_error, failures) from failures[-1][1]

    def uninstall(self) -> None:
        self.driver.stop()
        self.require_stopped()
        self.driver.remove_registration()
        self.driver.wait_removed()
        self.progress('Serviço removido da listagem. A limpeza de arquivos depende da escolha do usuário.')


class WindowsDriver:
    @staticmethod
    def run(*args):
        return subprocess.run(args, check=True, capture_output=True, text=True, errors='replace',
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def status(self):
        import win32service
        import win32serviceutil
        import pywintypes
        try:
            state = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
        except pywintypes.error as exc:
            if exc.winerror == 1060:
                return 'absent'
            raise
        return {win32service.SERVICE_STOPPED: 'stopped',
                win32service.SERVICE_RUNNING: 'running'}.get(state, 'pending')

    def stop(self):
        if self.status() in ('absent', 'stopped'):
            return
        import win32serviceutil
        import win32service
        win32serviceutil.StopService(SERVICE_NAME)
        win32serviceutil.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_STOPPED, 30)

    def start(self):
        import win32serviceutil
        import win32service
        if self.status() != 'running':
            win32serviceutil.StartService(SERVICE_NAME)
        win32serviceutil.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_RUNNING, 30)

    def wait_removed(self, timeout=30):
        deadline = time.monotonic() + timeout
        while self.status() != 'absent':
            if time.monotonic() >= deadline:
                raise RuntimeError('O Windows ainda lista o serviço para exclusão. Feche consoles de serviços abertos e tente novamente; nenhum arquivo foi limpo.')
            time.sleep(0.2)

    def launch_uninstaller(self, installation):
        executable = installation.directory / UNINSTALL_EXE
        if not executable.is_file():
            raise RuntimeError('O desinstalador não foi encontrado. Repare a instalação usando o setup atualizado.')
        subprocess.Popen([str(executable)], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def configure(self, installation: Installation, config: ApiConfig):
        import winreg
        executable = installation.directory / SERVICE_EXE
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY) as key:
            for name, value in [('ConfigPath', str(installation.config_path)),
                                ('InstallDir', str(installation.directory)),
                                ('Origins', installation.origins)]:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        action = 'create' if self.status() == 'absent' else 'config'
        self.run('sc.exe', action, SERVICE_NAME, 'binPath=', f'"{executable}"',
                 'start=', 'auto', 'obj=', SERVICE_ACCOUNT,
                 'DisplayName=', 'MockAíZé API')
        self.run('sc.exe', 'failure', SERVICE_NAME, 'reset=', '86400',
                 'actions=', 'restart/5000/restart/15000/restart/60000')
        self.run('sc.exe', 'failureflag', SERVICE_NAME, '1')
        # Data has no inherited Users ACL; token and state live beside config.json.
        # NetworkService provides machine credentials for remote SMB shares.
        root = installation.config_path.parent
        if not _is_network_path(root):
            self.run('icacls.exe', str(root), '/inheritance:r', '/grant:r',
                     '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', f'{SERVICE_SID}:(OI)(CI)M')
        if not _is_network_path(installation.directory):
            self.run('icacls.exe', str(installation.directory), '/grant', f'{SERVICE_SID}:(OI)(CI)RX')
        # Only local configured trees receive local SID grants. Remote SMB
        # permissions are controlled by the share and the machine account.
        for directory in dict.fromkeys((config.database_path.parent, config.presets_directory)):
            if not _is_network_path(directory):
                self.run('icacls.exe', str(directory), '/grant', f'{SERVICE_SID}:(OI)(CI)RX')
        self.configure_inputs(config, root)
        for directory in (config.output_directory, config.logs_directory):
            if not _is_network_path(directory):
                self.run('icacls.exe', str(directory), '/grant', f'{SERVICE_SID}:(OI)(CI)M')
        # NetworkService has SeChangeNotifyPrivilege by default, which permits
        # traversing parent directories without changing ACLs on the user's
        # profile, OneDrive root, or other unrelated ancestors.
        self.firewall(config, installation.origins, executable)
        self.register_shell(installation)

    def configure_inputs(self, config: ApiConfig, root: Path, *, allow_delete=True) -> None:
        if _is_network_path(config.input_directory):
            return
        # Replace only this SID's explicit grant, also removing a previous
        # cleanup delete grant when the policy is disabled again.
        # /grant:r alone does not clear a separate inherit-only delete ACE.
        # Remove this service SID's explicit grants, then restore its read grant.
        # Other SIDs, including the user's explicit rights, are untouched.
        self.run('icacls.exe', str(config.input_directory), '/remove:g', SERVICE_SID)
        self.run('icacls.exe', str(config.input_directory), '/grant:r', f'{SERVICE_SID}:(OI)(CI)RX')
        # The default input lives below the writable data root. Remove inherited
        # permissions from that subtree: the service can read files, and the
        # installing user can add/manage them without granting the service writes.
        if config.input_directory.is_relative_to(root):
            user_sid = _current_user_sid()
            self.run('icacls.exe', str(config.input_directory), '/inheritance:r', '/grant:r',
                     '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F',
                     f'*{user_sid}:(OI)(CI)M', f'{SERVICE_SID}:(OI)(CI)RX')
        if allow_delete and config.cleanup.inputs.mode == 'age':
            # Delete applies to inherited file objects, without granting write,
            # create, full control or delete access on the configured root.
            self.run('icacls.exe', str(config.input_directory), '/grant', f'{SERVICE_SID}:(OI)(IO)(DE)')

    def revoke_input_delete(self, config: ApiConfig, root: Path) -> None:
        if _is_network_path(config.input_directory) or not config.input_directory.exists():
            return
        self.configure_inputs(config, root, allow_delete=False)

    def firewall(self, config, origins, executable):
        # Exact product rule name only; never disable the firewall or touch unrelated rules.
        self.remove_firewall()
        if config.firewall_access == 'Y':
            self.run('netsh.exe', 'advfirewall', 'firewall', 'add', 'rule',
                     f'name={FIREWALL_RULE}', 'dir=in', 'action=allow', 'protocol=TCP',
                     f'localport={config.port}', f'remoteip={validate_origins(origins)}',
                     f'program={executable}', 'profile=private,domain', 'enable=yes')

    def remove_firewall(self):
        import win32com.client
        policy = win32com.client.Dispatch('HNetCfg.FwPolicy2')
        names = [rule.Name for rule in policy.Rules if rule.Name == FIREWALL_RULE]
        for name in names:
            policy.Rules.Remove(name)

    def register_shell(self, installation):
        import winreg
        import win32com.client
        exe = installation.directory / CONFIG_EXE
        key_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MockAiZeApi'
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            for name, value in [('DisplayName', 'MockAíZé API'),
                                ('DisplayVersion', '0.2.1'),
                                ('InstallLocation', str(installation.directory)),
                                ('DisplayIcon', f'"{exe}",0'),
                                ('UninstallString', f'"{installation.directory / UNINSTALL_EXE}"')]:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            winreg.SetValueEx(key, 'NoModify', 0, winreg.REG_DWORD, 1)
        shortcut = Path(os.environ['ProgramData']) / 'Microsoft/Windows/Start Menu/Programs/MockAíZé API — Configurar.lnk'
        shell = win32com.client.Dispatch('WScript.Shell')
        link = shell.CreateShortcut(str(shortcut))
        link.TargetPath = str(exe)
        link.WorkingDirectory = str(installation.directory)
        link.IconLocation = f'{exe},0'
        link.Save()

    def remove_registration(self):
        import winreg
        if self.status() != 'absent':
            self.run('sc.exe', 'delete', SERVICE_NAME)
        self.remove_firewall()
        for key in (REGISTRY_KEY, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MockAiZeApi'):
            try:
                winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, key)
            except FileNotFoundError:
                pass
        shortcut = Path(os.environ['ProgramData']) / 'Microsoft/Windows/Start Menu/Programs/MockAíZé API — Configurar.lnk'
        shortcut.unlink(missing_ok=True)

    def remove_binaries(self, directory: Path):
        # Running configurator cannot delete itself; Windows removes locked files at reboot.
        import win32api
        import win32con
        delayed = False
        for path in sorted(directory.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir() if path.is_dir() else path.unlink()
            except OSError as error:
                if not isinstance(error, PermissionError) and getattr(error, 'winerror', None) not in (5, 32, 33, 145):
                    raise
                win32api.MoveFileEx(str(path), None, win32con.MOVEFILE_DELAY_UNTIL_REBOOT)
                delayed = True
        try:
            directory.rmdir()
        except OSError:
            win32api.MoveFileEx(str(directory), None, win32con.MOVEFILE_DELAY_UNTIL_REBOOT)
            delayed = True
        return delayed


def discover_installation() -> Installation | None:
    if os.name != 'nt':
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY) as key:
            directory = Path(winreg.QueryValueEx(key, 'InstallDir')[0])
            config = Path(winreg.QueryValueEx(key, 'ConfigPath')[0])
            origins = winreg.QueryValueEx(key, 'Origins')[0]
        if not directory.is_absolute() or not config.is_absolute():
            raise RuntimeError('Registro da instalação inválido.')
        # Reject an unrelated service that happens to have the same name.
        import win32service
        import pywintypes
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            try:
                service = win32service.OpenService(scm, SERVICE_NAME, win32service.SERVICE_QUERY_CONFIG)
            except pywintypes.error as exc:
                if exc.winerror == 1060:
                    return Installation(directory, config, origins)
                raise
            try:
                binary = win32service.QueryServiceConfig(service)[3].strip('"')
                if Path(binary).resolve() != (directory / SERVICE_EXE).resolve():
                    raise RuntimeError('Serviço homônimo não pertence à instalação registrada.')
            finally:
                win32service.CloseServiceHandle(service)
        finally:
            win32service.CloseServiceHandle(scm)
        return Installation(directory, config, origins)
    except FileNotFoundError:
        if WindowsDriver().status() != 'absent':
            raise RuntimeError('Existe serviço homônimo sem registro do produto. Nenhuma alteração foi feita.')
        return None
