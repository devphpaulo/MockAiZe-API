"""Leitura limitada dentro da raiz autorizada, conferindo o handle aberto."""
import os
from pathlib import Path
import stat

from .errors import ApiError

MAX_INPUT = 2_000_000


def _opened_path(stream) -> Path:
    if os.name == 'nt':
        import ctypes
        import msvcrt
        from ctypes import wintypes
        function = ctypes.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
        function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        function.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = function(msvcrt.get_osfhandle(stream.fileno()), buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise OSError
        value = buffer.value
        if value.startswith('\\\\?\\UNC\\'):
            value = '\\\\' + value[8:]
        elif value.startswith('\\\\?\\'):
            value = value[4:]
        return Path(value).resolve(strict=True)
    return Path(os.readlink(f'/proc/self/fd/{stream.fileno()}')).resolve(strict=True)


def read_input_file(root: Path, value: str) -> str:
    forbidden = ApiError(422, 'INPUT_FILE_PATH_FORBIDDEN', 'O arquivo deve ser um XML dentro da pasta autorizada.')
    path = Path(value)
    if not path.is_absolute() or path.suffix.lower() != '.xml':
        raise forbidden
    try:
        canonical_root = root.resolve(strict=True)
        canonical = path.resolve(strict=True)
        if not canonical.is_relative_to(canonical_root):
            raise forbidden
        with canonical.open('rb') as stream:
            opened = _opened_path(stream)
            info = os.fstat(stream.fileno())
            if not opened.is_relative_to(canonical_root) or not stat.S_ISREG(info.st_mode):
                raise forbidden
            if info.st_size > MAX_INPUT:
                raise ApiError(413, 'INPUT_TOO_LARGE', 'O XML de entrada excede 2 MB.')
            content = stream.read(MAX_INPUT + 1)
            if len(content) > MAX_INPUT:
                raise ApiError(413, 'INPUT_TOO_LARGE', 'O XML de entrada excede 2 MB.')
        return content.decode('utf-8-sig')
    except FileNotFoundError:
        # Não revelar existência de caminhos fora da raiz mesmo se ausentes.
        if not path.resolve().is_relative_to(root.resolve()):
            raise forbidden from None
        raise ApiError(404, 'INPUT_FILE_NOT_FOUND', 'Arquivo de entrada não encontrado.') from None
    except UnicodeError:
        raise ApiError(422, 'INPUT_XML_INVALID', 'O XML de entrada deve usar UTF-8.') from None
    except OSError:
        raise forbidden from None
