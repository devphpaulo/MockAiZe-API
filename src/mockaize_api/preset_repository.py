"""Read-only C-PRESET-1 files and Site synchronization markers."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from .errors import ApiError
from .preset_codec import PresetError, decode_preset


def _api_error(code, message):
    return ApiError(503, code, message)


def _safe_component(value):
    if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value)
            or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])', value, re.I)):
        raise ValueError('invalid component')
    return value


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('invalid UUID')
    return value


def _ordinary(path, *, directory=False):
    """Reject links, reparse points and non-regular paths without following them."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise _api_error('PRESET_INVALID', 'O catálogo de presets contém um caminho inválido.')
    return True


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate property')
        result[key] = value
    return result


def _validate_journal(journal, operation_id):
    keys = {'schemaVersion', 'operationId', 'rootId', 'kind', 'catalogWide', 'affectedIds', 'createdAt', 'files'}
    if (not isinstance(journal, dict) or set(journal) != keys or type(journal['schemaVersion']) is not int
            or journal['schemaVersion'] != 1 or _uuid(journal['operationId']) != operation_id):
        raise ValueError('invalid journal envelope')
    _uuid(journal['rootId'])
    if journal['kind'] not in {'config-save', 'metadata', 'batch', 'backfill', 'import', 'restore'}:
        raise ValueError('invalid journal kind')
    ids = journal['affectedIds']
    if (type(journal['catalogWide']) is not bool or not isinstance(ids, list)
            or any(not isinstance(item, str) for item in ids) or ids != sorted(set(ids))):
        raise ValueError('invalid journal IDs')
    for identifier in ids:
        _safe_component(identifier)
    if not isinstance(journal['createdAt'], str):
        raise ValueError('invalid journal date')
    datetime.fromisoformat(journal['createdAt'])
    if not isinstance(journal['files'], list):
        raise ValueError('invalid journal files')
    seen = set()
    for entry in journal['files']:
        if not isinstance(entry, dict) or set(entry) != {'final', 'before', 'after'}:
            raise ValueError('invalid journal entry')
        final = entry['final']
        if not isinstance(final, str):
            raise ValueError('invalid journal target')
        match = re.fullmatch(r'([A-Za-z0-9_-]+)(\.OLD)?\.mockaize\.xml', final)
        if (not match or match[1] not in ids or final.casefold() in seen
                or _safe_component(match[1]) != match[1]):
            raise ValueError('invalid journal target')
        seen.add(final.casefold())
        role = 'old' if match[2] else 'current'
        for side in ('before', 'after'):
            snapshot = entry[side]
            if not isinstance(snapshot, dict) or type(snapshot.get('exists')) is not bool:
                raise ValueError('invalid journal snapshot')
            if snapshot['exists']:
                expected = f".{operation_id}.{match[1]}.{role}.{side}.tmp"
                if (set(snapshot) != {'exists', 'staged', 'sha256'} or snapshot['staged'] != expected
                        or not isinstance(snapshot['sha256'], str)
                        or not re.fullmatch(r'[0-9a-f]{64}', snapshot['sha256'])):
                    raise ValueError('invalid journal snapshot reference')
            elif set(snapshot) != {'exists'}:
                raise ValueError('invalid absent snapshot')
    return journal


class PresetRepository:
    """Loads each request from disk; it never creates, repairs, or caches presets."""
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def available(self):
        """Availability-only preflight; payload validation is deferred to requests."""
        return self._root()

    def _root(self):
        try:
            exists = _ordinary(self.directory, directory=True)
            if not exists:
                return False
            with os.scandir(self.directory):
                pass
        except ApiError:
            raise
        except OSError:
            raise _api_error('DEPENDENCY_UNAVAILABLE', 'O diretório de presets não está acessível.') from None
        return True

    def _journals(self):
        try:
            if not self._root():
                return []
            sync = self.directory / '.sync'
            if not _ordinary(sync, directory=True):
                return []
            journals = []
            with os.scandir(sync) as entries:
                paths = sorted((Path(entry.path) for entry in entries), key=lambda item: item.name)
            for path in paths:
                if path.name.casefold().endswith('.pending.json.tmp'):
                    _ordinary(path)
                    continue  # A journal is pending only after its atomic publication.
                if not path.name.endswith('.pending.json'):
                    raise ValueError('unknown sync entry')
                _ordinary(path)
                operation_id = _uuid(path.name.removesuffix('.pending.json'))
                raw = path.read_bytes()
                journal = json.loads(raw, object_pairs_hook=_json_pairs)
                journals.append(_validate_journal(journal, operation_id))
            return journals
        except ApiError:
            raise
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError, RecursionError):
            raise _api_error('PRESET_SYNC_UNAVAILABLE', 'Não foi possível verificar a sincronização do catálogo.') from None

    def pending(self, variation_id=None):
        return any(variation_id is None or journal['catalogWide'] or variation_id in journal['affectedIds']
                   for journal in self._journals())

    def verify_scan(self, scan):
        """Reject a catalog changed while its SQLite fallback was being read."""
        current = self._scan_once()
        if current['fingerprint'] != scan['fingerprint'] or current['available'] != scan['available']:
            self._sync_pending()

    def verify_fallback(self, variation_id):
        """A newly published current supersedes the SQLite fallback snapshot."""
        if self.current(variation_id)[1] is not None:
            self._sync_pending()

    @staticmethod
    def _sync_pending():
        raise _api_error('PRESET_SYNC_PENDING', 'A configuração está sendo sincronizada. Tente novamente.')

    @staticmethod
    def _invalid_preset():
        raise _api_error('PRESET_INVALID', 'Um preset está inválido ou usa um formato não suportado.')

    def current(self, variation_id):
        """Return (directory available, payload, unreadable current file)."""
        try:
            _safe_component(variation_id)
            if self.pending(variation_id):
                self._sync_pending()
            available = self._root()
            if not available:
                return False, None, False
            path = self.directory / f'{variation_id}.mockaize.xml'
            try:
                exists = _ordinary(path)
            except OSError:
                if self.pending(variation_id):
                    self._sync_pending()
                return True, None, True
            if not exists:
                if self.pending(variation_id):
                    self._sync_pending()
                return True, None, False
            try:
                raw = path.read_bytes()
            except OSError:
                if self.pending(variation_id):
                    self._sync_pending()
                return True, None, True
            payload = decode_preset(raw)
            if payload['metadata']['id'] != variation_id:
                self._invalid_preset()
            if self.pending(variation_id):
                self._sync_pending()
            return True, payload, False
        except ApiError:
            raise
        except (PresetError, OSError, ValueError, TypeError, RecursionError, OverflowError):
            self._invalid_preset()

    def _scan_once(self):
        if self.pending():
            self._sync_pending()
        available = self._root()
        if not available:
            return {'available': False, 'items': {}, 'inaccessible': set(), 'fingerprint': ()}
        items, inaccessible, fingerprint, seen = {}, set(), [], set()
        try:
            with os.scandir(self.directory) as entries:
                paths = sorted((Path(entry.path) for entry in entries), key=lambda item: item.name.casefold())
        except OSError:
            raise _api_error('DEPENDENCY_UNAVAILABLE', 'O diretório de presets não está acessível.') from None
        for path in paths:
            lower = path.name.casefold()
            if lower.endswith('.old.mockaize.xml') or not lower.endswith('.mockaize.xml'):
                continue
            if not path.name.endswith('.mockaize.xml'):
                self._invalid_preset()
            identifier = path.name[:-len('.mockaize.xml')]
            try:
                _safe_component(identifier)
                if identifier.casefold() in seen:
                    self._invalid_preset()
                seen.add(identifier.casefold())
                if not _ordinary(path):
                    continue
                raw = path.read_bytes()
            except ApiError:
                raise
            except (ValueError, TypeError, RecursionError):
                self._invalid_preset()
            except OSError:
                inaccessible.add(identifier)
                fingerprint.append((identifier, None))
                continue
            try:
                payload = decode_preset(raw)
            except PresetError:
                self._invalid_preset()
            if payload['metadata']['id'] != identifier:
                self._invalid_preset()
            items[identifier] = payload
            fingerprint.append((identifier, hashlib.sha256(raw).hexdigest()))
        if self.pending():
            self._sync_pending()
        return {'available': True, 'items': items, 'inaccessible': inaccessible,
                'fingerprint': tuple(fingerprint)}

    def scan(self):
        """Double-collect to detect a completed multi-file publication during listing."""
        first = self._scan_once()
        second = self._scan_once()
        if first['fingerprint'] != second['fingerprint'] or first['available'] != second['available']:
            self._sync_pending()
        return second
