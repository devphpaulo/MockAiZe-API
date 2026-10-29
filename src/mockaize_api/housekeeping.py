"""One cancellable startup round; file deletion is confined to validated roots."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import stat
import threading

from .config import ConfigurationError, validate_cleanup_paths
from .errors import ApiError
from .inputs import _opened_path
from .publication import safe_filename


class UnsafePath(ValueError):
    pass


def _reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def protected_paths(config, config_path, binaries=()):
    paths = [Path(config_path), config_path.parent / 'credentials.json', config_path.parent / 'policy.json',
             config.presets_directory, *binaries]
    for database in (config.database_path, config_path.parent / 'api-state.sqlite3'):
        paths.extend(Path(str(database) + suffix) for suffix in ('', '-wal', '-shm', '-journal'))
    return tuple(path.resolve() for path in paths)


def _no_reparse(path):
    for candidate in (path, *path.parents):
        try:
            if _reparse(candidate.lstat()):
                raise UnsafePath
        except FileNotFoundError:
            continue


def _guard_file(path, root, protected=()):
    if path == root or not path.is_relative_to(root):
        raise UnsafePath
    _no_reparse(path)
    if root.resolve(strict=True) != root or path.resolve(strict=True) != path:
        raise UnsafePath
    if any(path == item or path.is_relative_to(item) for item in protected):
        raise UnsafePath
    info = path.lstat()
    if _reparse(info) or not stat.S_ISREG(info.st_mode):
        raise UnsafePath
    return info


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _file_date(info):
    return datetime.fromtimestamp(info.st_mtime).astimezone().date()


@contextmanager
def _delete_stream(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            yield stream
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    # DELETE + GENERIC_READ; no FILE_SHARE_DELETE, no delete-on-open, no force flags.
    handle = create(str(path), 0x10000 | 0x80000000, 3, None, 3, 0x200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close(handle)
        raise
    with os.fdopen(descriptor, 'rb') as stream:
        yield stream


def _windows_dispose(stream):
    import ctypes
    import msvcrt
    from ctypes import wintypes
    class Disposition(ctypes.Structure):
        _fields_ = [('DeleteFile', ctypes.c_ubyte)]  # Windows BOOLEAN, one byte.
    function = ctypes.WinDLL('kernel32', use_last_error=True).SetFileInformationByHandle
    function.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    function.restype = wintypes.BOOL
    disposition = Disposition(1)
    if not function(msvcrt.get_osfhandle(stream.fileno()), 4, ctypes.byref(disposition),
                    ctypes.sizeof(disposition)):
        raise ctypes.WinError(ctypes.get_last_error())


def _posix_unlink(path, root, opened_info):
    descriptors = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current = os.open(root, flags)
        descriptors.append(current)
        for name in path.relative_to(root).parts[:-1]:
            current = os.open(name, flags, dir_fd=current)
            descriptors.append(current)
        parent = Path(os.readlink(f'/proc/self/fd/{current}')).resolve(strict=True)
        if parent != path.parent or not parent.is_relative_to(root):
            raise UnsafePath
        info = os.stat(path.name, dir_fd=current, follow_symlinks=False)
        if _reparse(info) or _identity(info) != _identity(opened_info):
            raise UnsafePath
        os.unlink(path.name, dir_fd=current)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _delete_file(path, root, cutoff, protected, stop_event=None):
    before = _guard_file(path, root, protected)
    if _file_date(before) >= cutoff:
        return False
    with _delete_stream(path) as stream:
        opened = _opened_path(stream)
        info = os.fstat(stream.fileno())
        if opened != path or not opened.is_relative_to(root) or _reparse(info) or not stat.S_ISREG(info.st_mode):
            raise UnsafePath
        current = _guard_file(path, root, protected)
        if _identity(info) != _identity(current) or _identity(before) != _identity(current):
            return False
        if _file_date(info) >= cutoff:
            return False
        if stop_event is not None and stop_event.is_set():
            return False
        if os.name == 'nt':
            _windows_dispose(stream)
        else:
            _posix_unlink(path, root, info)
    return True


class FileActivity:
    """Tiny memory-only claims; cleanup never holds a lock during filesystem I/O."""
    def __init__(self):
        self.lock = threading.Lock()
        self.generations = 0
        self.readers = {}
        self.deleting = set()

    def begin_generation(self):
        with self.lock:
            self.generations += 1

    def end_generation(self):
        with self.lock:
            self.generations -= 1

    @contextmanager
    def generation(self):
        self.begin_generation()
        try:
            yield
        finally:
            self.end_generation()

    @contextmanager
    def replay(self, paths):
        with self.lock:
            if any(path in self.deleting for path in paths):
                raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'O artefato está temporariamente ocupado.')
            for path in paths:
                self.readers[path] = self.readers.get(path, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                for path in paths:
                    self.readers[path] -= 1
                    if not self.readers[path]:
                        del self.readers[path]

    @contextmanager
    def cleanup(self, path):
        with self.lock:
            allowed = not self.generations and not self.readers.get(path) and path not in self.deleting
            if allowed:
                self.deleting.add(path)
        try:
            yield allowed
        finally:
            if allowed:
                with self.lock:
                    self.deleting.remove(path)


class Housekeeping:
    def __init__(self, config, policy, config_path, log, *, activity=None, stop_event=None,
                 today=None, retry_seconds=1, binaries=()):
        self.config, self.config_path, self.binaries = config, Path(config_path), binaries
        self.protected = None
        try:
            self._validate_paths()
        except OSError:
            pass  # Transient cleanup I/O belongs to the startup worker's retries.
        self.roots = []
        startup_date = today or datetime.now().astimezone().date()
        for name, directory in (('inputs', config.input_directory), ('outputs', config.output_directory),
                                ('logs', config.logs_directory)):
            days = getattr(policy, 'cleanup_' + name + '_days')
            if days is None:
                continue
            try:
                _no_reparse(directory)
            except UnsafePath:
                raise ConfigurationError('cleanup.' + name, 'A limpeza não atravessa links ou junções.') from None
            except OSError:
                pass
            cutoff = date.min if days >= startup_date.toordinal() else startup_date - timedelta(days=days)
            try:
                canonical = directory.resolve()
            except OSError:
                canonical = Path(os.path.abspath(directory))
            self.roots.append((name, canonical, cutoff))
        self.activity = activity or FileActivity()
        self.log = log
        self.stop_event = stop_event or threading.Event()
        self.retry_seconds = retry_seconds
        self.counts = {'scanned': 0, 'deleted': 0, 'skipped': 0, 'failures': 0, 'attempts': 0}
        self.finished = threading.Event()
        self.thread = None
        self.start_lock = threading.Lock()

    def _validate_paths(self):
        protected = protected_paths(self.config, self.config_path, self.binaries)
        validate_cleanup_paths(self.config, protected)
        self.protected = protected

    def start(self):
        with self.start_lock:
            if self.thread is not None:
                return False
            self.thread = threading.Thread(target=self._run, name='mockaize-startup-cleanup', daemon=True)
            self.thread.start()
            return True

    def stop(self, timeout=0.25):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout)
        return self.thread is None or not self.thread.is_alive()

    def _event(self, event, **values):
        try:
            self.log.write(event=event, method='HOUSEKEEPING', route='service', **values)
        except (ApiError, OSError):
            pass

    def _run(self):
        pending = self.roots
        delay = self.retry_seconds
        try:
            self._event('HOUSEKEEPING_STARTED')
            while pending and not self.stop_event.is_set():
                self.counts['attempts'] += 1
                if self.protected is None:
                    try:
                        self._validate_paths()
                    except OSError:
                        self.counts['failures'] += 1
                        self._event('HOUSEKEEPING_FAILURE', code='DIRECTORY_UNAVAILABLE')
                        if self.stop_event.wait(delay):
                            break
                        delay = min(30, delay * 2)
                        continue
                retry = []
                for name, root, cutoff in pending:
                    if self.stop_event.is_set():
                        break
                    try:
                        if self._scan_root(root, cutoff):
                            retry.append((name, root, cutoff))
                    except (OSError, ValueError):
                        self.counts['failures'] += 1
                        self._event('HOUSEKEEPING_FAILURE', code='DIRECTORY_UNAVAILABLE', cleanupScope=name)
                        retry.append((name, root, cutoff))
                pending = retry
                if pending and self.stop_event.wait(delay):
                    break
                delay = min(30, delay * 2)
        except Exception:
            self.counts['failures'] += 1
            self._event('HOUSEKEEPING_FAILURE', code='CLEANUP_FAILED')
        finally:
            self._event('HOUSEKEEPING_COMPLETED', result='cancelled' if self.stop_event.is_set() else 'completed',
                        **self.counts)
            self.finished.set()

    def _scan_root(self, root, cutoff):
        if cutoff == date.min:
            return False
        retry = False
        stack = [root]
        while stack and not self.stop_event.is_set():
            directory = stack.pop()
            _no_reparse(directory)
            if directory.resolve(strict=True) != directory or not directory.is_relative_to(root):
                raise UnsafePath
            with os.scandir(directory) as entries:
                for entry in entries:
                    if self.stop_event.is_set():
                        break
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if _reparse(info):
                            self.counts['skipped'] += 1
                            continue
                        path = directory / entry.name
                        if stat.S_ISDIR(info.st_mode):
                            stack.append(path)
                            continue
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        self.counts['scanned'] += 1
                        if _file_date(info) >= cutoff:
                            continue
                        with self.activity.cleanup(path) as allowed:
                            if not allowed:
                                retry = True
                                continue
                            if self.stop_event.is_set():
                                break
                            if _delete_file(path, root, cutoff, self.protected, self.stop_event):
                                self.counts['deleted'] += 1
                    except FileNotFoundError:
                        continue
                    except UnsafePath:
                        self.counts['skipped'] += 1
                    except (OSError, ValueError):
                        retry = True
                        self.counts['failures'] += 1
                        self._event('HOUSEKEEPING_FAILURE', code='FILE_DELETE_FAILED')
        return retry


def _directory_files(response):
    if response['status'] != 200 or 'application/json' not in response['headers'].get('Content-Type', ''):
        return None
    try:
        value = json.loads(response['body'])
        if value.get('delivery') != 'directory':
            return None
        files = value['files']
        if not isinstance(files, list) or not files:
            raise ValueError
        for item in files:
            safe_filename(item['fileName'])
            if type(item['sizeBytes']) is not int or item['sizeBytes'] < 0 or not isinstance(item['sha256'], str):
                raise ValueError
        return files
    except (ValueError, KeyError, TypeError, AttributeError, ApiError):
        raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Metadados do replay indisponíveis.') from None


def verify_directory_replay(response, root, activity):
    files = _directory_files(response)
    if files is None:
        return
    expired = ApiError(410, 'OUTPUT_EXPIRED', 'O arquivo original não está mais disponível. Nenhuma geração foi repetida.')
    try:
        _no_reparse(root)
        canonical_root = root.resolve(strict=True)
        paths = [canonical_root / item['fileName'] for item in files]
        with activity.replay(paths):
            for item, path in zip(files, paths):
                before = _guard_file(path, canonical_root)
                with path.open('rb') as stream:
                    info = os.fstat(stream.fileno())
                    if (_opened_path(stream) != path or not stat.S_ISREG(info.st_mode)
                            or info.st_size != item['sizeBytes'] or _identity(before) != _identity(info)):
                        raise expired
                    digest = hashlib.sha256()
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                    if (digest.hexdigest() != item['sha256'] or _identity(os.fstat(stream.fileno())) != _identity(info)
                            or _identity(_guard_file(path, canonical_root)) != _identity(info)):
                        raise expired
    except UnsafePath:
        raise expired from None
    except OSError as error:
        network_errors = {53, 64, 67, 121, 1231, 1232}
        if isinstance(error, FileNotFoundError) and getattr(error, 'winerror', None) not in network_errors:
            raise expired from None
        raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Não foi possível verificar o artefato original.') from None
