"""Desinstalação em duas fases: remover serviço, depois limpeza opt-in."""
import json
import os
from pathlib import Path
import shutil
import stat

from .config import ConfigurationError, load_config
from .windows_ops import Installation, Installer, WindowsDriver, discover_installation


def _reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _protected_paths():
    home = Path.home().resolve()
    paths = {home, home / 'Documents', home / 'Desktop', home / 'Downloads'}
    for name in ['SystemRoot', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData', 'PUBLIC']:
        value = os.environ.get(name)
        if value:
            paths.add(Path(value).resolve())
    return paths


def checked_directory(path: Path, database: Path | None = None) -> Path:
    """Confira o destino absoluto e seus links antes de qualquer remoção."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('O destino de limpeza deve ser absoluto.')
    for ancestor in (path, *path.parents):
        if ancestor.exists() and _reparse(ancestor):
            raise ValueError('Limpeza automática não atravessa links ou junções.')
    resolved = path.resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError('A raiz de um disco não pode ser removida.')
    protected = _protected_paths()
    if database is not None:
        protected.add(database.resolve())
    if any(item == resolved or item.is_relative_to(resolved) for item in protected):
        raise ValueError('A pasta contém um local protegido ou o banco de origem do estúdio.')
    return resolved


def _check_tree(path: Path):
    if not path.exists():
        return
    if not path.is_dir():
        raise ValueError('O destino de limpeza não é um diretório.')
    for root, directories, files in os.walk(path, followlinks=False):
        for name in directories + files:
            child = Path(root) / name
            if _reparse(child) or not child.resolve().is_relative_to(path):
                raise ValueError('A pasta contém link ou junção; os dados foram preservados.')


class UninstallSession:
    def __init__(self, installation: Installation, driver=None):
        self.installation = installation
        self.driver = driver or WindowsDriver()
        self.detached = False
        self.config = None
        self.folders = []
        # Read paths before removing the product registry or config.json.
        try:
            self.config = load_config(installation.config_path)
        except ConfigurationError:
            return
        candidates = [self.config.input_directory, self.config.output_directory,
                      self.config.logs_directory, installation.config_path.parent]
        for path in candidates:
            try:
                canonical = checked_directory(path, self.config.database_path)
            except (ValueError, OSError):
                continue
            if canonical not in self.folders and canonical != installation.directory.resolve():
                self.folders.append(canonical)
        self.folders = [path for path in self.folders if not any(
            parent != path and path.is_relative_to(parent) for parent in self.folders)]

    def detach(self):
        Installer(self.installation, self.driver).uninstall()
        self.detached = True

    def cleanup(self, binaries: bool = False, folders=()):
        if not self.detached:
            raise RuntimeError('Confirme primeiro a remoção do serviço no Windows.')
        selected = []
        for path in folders:
            candidate = Path(path)
            if candidate.resolve() not in self.folders:
                raise ValueError('Pasta não autorizada para esta desinstalação.')
            canonical = checked_directory(candidate, self.config.database_path)
            _check_tree(canonical)
            selected.append(canonical)
        target = None
        if binaries:
            target = checked_directory(self.installation.directory,
                                       self.config.database_path if self.config else None)
            _check_tree(target)
        # Every destination is checked before deleting the first one.
        for folder in sorted(set(selected), key=lambda path: len(path.parts), reverse=True):
            if folder.exists():
                shutil.rmtree(folder)
        restart = bool(self.driver.remove_binaries(target)) if target else False
        return {'restartRequired': restart, 'removedFolders': [str(path) for path in selected],
                'binariesSelected': binaries}


def finish_uninstall(session: UninstallSession, ask):
    """Perguntas só ocorrem após a exclusão confirmada do serviço."""
    if not session.detached:
        raise RuntimeError('O serviço ainda não foi removido.')
    binaries = ask('binaries', session.installation.directory)
    folders = [path for path in session.folders if ask('folder', path)]
    return session.cleanup(binaries, folders)


def discover_uninstall_target(executable: Path) -> Installation | None:
    installation = discover_installation()
    if installation is not None:
        return installation
    # A receipt permits later cleanup when the user first elected to keep files.
    receipt = executable.parent / 'installation.json'
    if not receipt.is_file():
        return None
    try:
        value = json.loads(receipt.read_text(encoding='utf-8'))
        directory, config = Path(value['directory']), Path(value['configPath'])
        if (value['product'] != 'MockAiZe API' or value['version'] != 1
                or not directory.is_absolute() or not config.is_absolute()
                or directory.resolve() != executable.parent.resolve()):
            raise ValueError
        checked_directory(directory)
        return Installation(directory, config, value.get('origins', 'LocalSubnet'))
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError('O registro local da instalação é inválido; nenhum arquivo foi removido.') from None
