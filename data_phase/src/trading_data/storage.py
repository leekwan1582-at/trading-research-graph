import hashlib
import json
import os
from pathlib import Path
import tempfile

from .validation import DataRejected


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def confined(root: Path, relative: str) -> Path:
    root = root.resolve(strict=True)
    value = Path(relative)
    if value.is_absolute():
        raise DataRejected('paths must be project-relative')
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise DataRejected('path escapes project root')
    return path


def limited_read(path: Path, maximum: int) -> bytes:
    if not path.is_file():
        raise DataRejected(f'file missing: {path}')
    with path.open('rb') as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise DataRejected(f'input exceeds byte cap: {path.name}')
    return value


def publish(root: Path, relative: str, blob: bytes) -> dict:
    """POSIX same-filesystem, complete-file publication; safe same-content retry."""
    target = confined(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            existing = limited_read(target, max(len(blob), 1))
            if existing != blob:
                raise DataRejected(f'artifact conflict or corruption: {relative}')
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'path': relative, 'sha256': digest(blob), 'bytes': len(blob)}
