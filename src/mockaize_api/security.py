"""Chave de alta entropia exibida apenas na criação; só o hash é persistido."""
import hashlib
import hmac
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
import re

from .errors import ApiError


def credential_path(config_path: Path) -> Path:
    return config_path.parent / 'credentials.json'


def create_credentials(config_path: Path, rotate: bool = False) -> str:
    target = credential_path(config_path)
    if target.exists() and not rotate:
        raise ApiError(409, 'CREDENTIALS_EXIST', 'Já existe uma chave. Solicite rotação explicitamente.')
    token = secrets.token_urlsafe(48)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent,
                                         prefix='.credentials-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'version': 1, 'sha256': hashlib.sha256(token.encode()).hexdigest()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        if rotate:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
    except OSError:
        raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Não foi possível proteger a credencial.') from None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return token


def key_digest(config_path: Path) -> str:
    try:
        data = json.loads(credential_path(config_path).read_text(encoding='utf-8'))
        digest = data['sha256']
        if data['version'] != 1 or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError
        int(digest, 16)
        return digest
    except (OSError, ValueError, KeyError, TypeError):
        raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Credencial indisponível.') from None


def verify_key(config_path: Path, token: str) -> bool:
    if not isinstance(token, str) or len(token) > 1024:
        return False
    return hmac.compare_digest(key_digest(config_path), hashlib.sha256(token.encode()).hexdigest())


@dataclass(frozen=True)
class AuthContext:
    authenticated: bool = False
    method: str = 'none'


def _unauthorized():
    return ApiError(401, 'UNAUTHORIZED', 'Credencial ausente, inválida ou expirada.')


def _credential_header(keys: list[str], authorizations: list[str]) -> tuple[str, str | None]:
    if len(keys) > 1 or len(authorizations) > 1 or (keys and authorizations):
        raise ApiError(400, 'INVALID_REQUEST', 'Envie somente uma credencial de autenticação.')
    if keys:
        key = keys[0]
        if not isinstance(key, str) or not re.fullmatch(r'[\x21-\x7e]{1,1024}', key):
            raise ApiError(400, 'INVALID_REQUEST', 'Header de autenticação inválido.')
        return 'apiKey', key
    if authorizations:
        value = authorizations[0]
        match = re.fullmatch(r'(?i:Bearer) +([A-Za-z0-9._~+/-]+=*)', value) if isinstance(value, str) else None
        if match is None or len(value) > 1024:
            raise ApiError(400, 'INVALID_REQUEST', 'Header de autenticação inválido.')
        return 'bearer', match[1]
    return 'none', None


class Authenticator:
    """Installation credentials and opaque 30-minute tokens; no persisted sessions."""
    lifetime_seconds = 1800

    def __init__(self, config_path: Path, *, clock=time.monotonic):
        self.config_path = config_path
        self.clock = clock
        self.lock = threading.Lock()
        self.digest = None
        self.tokens = {}

    def _current_digest(self):
        digest = key_digest(self.config_path)
        if self.digest != digest:
            self.tokens.clear()
            self.digest = digest
        return digest

    @staticmethod
    def _matches_key(digest, key):
        return hmac.compare_digest(digest, hashlib.sha256(key.encode()).hexdigest())

    def authenticate(self, keys: list[str], authorizations: list[str], *, required=True,
                     key_only=False) -> AuthContext:
        method, value = _credential_header(keys, authorizations)
        if method == 'none':
            if required or key_only:
                raise _unauthorized()
            return AuthContext()
        if key_only and method != 'apiKey':
            raise _unauthorized()
        with self.lock:
            digest = self._current_digest()
            if method == 'apiKey':
                if not self._matches_key(digest, value):
                    raise _unauthorized()
                return AuthContext(True, method)
            token_hash = hashlib.sha256(value.encode()).hexdigest()
            expires_at = self.tokens.get(token_hash)
            if expires_at is None or self.clock() >= expires_at:
                self.tokens.pop(token_hash, None)
                raise _unauthorized()
            return AuthContext(True, method)

    def issue(self, keys: list[str], authorizations: list[str]) -> dict:
        method, key = _credential_header(keys, authorizations)
        if method != 'apiKey':
            raise _unauthorized()
        with self.lock:
            # Verification and token binding use the same credential snapshot.
            # A concurrent external rotation makes this token invalid on use;
            # it can never turn an old key into a session for the new key.
            digest = self._current_digest()
            if not self._matches_key(digest, key):
                raise _unauthorized()
            now = self.clock()
            self.tokens = {token: expiry for token, expiry in self.tokens.items() if expiry > now}
            token = secrets.token_urlsafe(48)
            self.tokens[hashlib.sha256(token.encode()).hexdigest()] = now + self.lifetime_seconds
        return {'access_token': token, 'token_type': 'Bearer', 'expires_in': self.lifetime_seconds}
