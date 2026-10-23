"""Publicação sem sobrescrita, com compensação de falha entre arquivos."""
import hashlib
import os
from pathlib import Path
import re
import tempfile
import uuid
from decimal import Decimal, ROUND_HALF_UP

from .errors import ApiError


def metadata(content: bytes) -> dict:
    size = len(content)
    display = f'{size} B'
    if size >= 1_000_000:
        display = f'{(Decimal(size) / 1_000_000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)} MB'
    elif size >= 1000:
        display = f'{(Decimal(size) / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)} KB'
    return {'sha256': hashlib.sha256(content).hexdigest(), 'sizeBytes': size, 'sizeDisplay': display}


def safe_filename(name: str) -> str:
    if (not isinstance(name, str) or not name or len(name) > 180
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith(('.', ' '))
            or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', name, re.I)
            or not name.lower().endswith('.xml')):
        raise ApiError(422, 'INVALID_FILE_NAME', 'A fórmula produziu um nome de arquivo inválido.')
    return name


def publish(directory: Path, documents: list[dict]) -> list[dict]:
    for document in documents:
        safe_filename(document['fileName'])
    published, temporary, results = [], [], []
    try:
        for document in documents:
            content = document['content']
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.mockaize-', delete=False) as stream:
                staging = Path(stream.name)
                temporary.append(staging)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            name = document['fileName']
            for attempt in range(20):
                destination = directory / name
                try:
                    os.link(staging, destination)
                    break
                except FileExistsError:
                    name = f'{Path(document["fileName"]).stem[:145]}_{uuid.uuid4().hex[:16]}.xml'
            else:
                raise OSError('collision')
            published.append(destination)
            item = {key: value for key, value in document.items() if key != 'content'}
            item.update(fileName=name, **metadata(content))
            if name != document['fileName']:
                item['collisionRenamed'] = True
            results.append(item)
        return results
    except OSError:
        residue = []
        for destination in published:
            try:
                destination.unlink()
            except OSError:
                residue.append(destination.name)
        if residue:
            raise ApiError(500, 'OUTPUT_PARTIAL_FAILURE', 'Falha de publicação; intervenção administrativa necessária.', residue=residue) from None
        raise ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'Não foi possível publicar os arquivos.') from None
    finally:
        for staging in temporary:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                pass
