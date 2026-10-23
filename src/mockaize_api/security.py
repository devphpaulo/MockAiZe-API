"""Chave de alta entropia exibida apenas na criação; só o hash é persistido."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile

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
