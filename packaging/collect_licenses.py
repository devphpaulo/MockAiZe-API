"""Copy unmodified licensing material supplied by installed runtime wheels."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys


def collect(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for package in ('PySide6-Essentials', 'shiboken6', 'pyinstaller', 'pywin32', 'tzdata'):
        dist = distribution(package)
        target = destination / package
        target.mkdir(exist_ok=True)
        for entry in dist.files or []:
            name = str(entry).lower()
            if not any(word in name for word in ('license', 'copying', 'notice')) and not name.endswith('.dist-info/metadata'):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file():
                continue
            relative = Path(*[part for part in entry.parts if part not in ('..', '.')])
            copied = target / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copied)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.is_file():
        raise RuntimeError('A licença da distribuição Python não foi encontrada.')
    shutil.copy2(python_license, destination / 'PYTHON-LICENSE.txt')
    notices = Path(__file__).resolve().parent.parent / 'THIRD_PARTY_NOTICES.md'
    if notices.is_file():
        shutil.copy2(notices, destination / notices.name)
    additional = Path(__file__).resolve().parent / 'licenses'
    if additional.is_dir():
        shutil.copytree(additional, destination / 'free-software-terms', dirs_exist_ok=True)


if __name__ == '__main__':
    collect(Path(sys.argv[1]))
