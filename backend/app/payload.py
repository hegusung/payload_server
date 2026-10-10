"""
Payload assembly — the single source of truth for the final bytes a client receives.

Both delivery modes use this:
  - self-serve (app/api/serve.py) streams the result over the serving port
  - cloud deploy (app/providers/*) uploads the result to an object store

Pipeline: raw file bytes -> transform pipeline -> prepend/append magic+random padding.
"""
from __future__ import annotations

import os
import random
import string
from pathlib import Path

from app.db import ContentTypePreset, HostedFile


def _random_pad(n: int, charset: str) -> bytes:
    if n <= 0:
        return b''
    if charset == 'alphanum':
        return bytes(random.choices((string.ascii_letters + string.digits).encode(), k=n))
    elif charset == 'printable':
        return bytes(random.choices(string.printable[:94].encode(), k=n))
    else:
        return os.urandom(n)


def _apply_magic(total: int, magic_hex: str, charset: str, is_prepend: bool) -> bytes:
    """Build a padding block of `total` bytes using magic bytes as an anchor."""
    if total <= 0:
        return b''
    try:
        magic = bytes.fromhex(magic_hex) if magic_hex else b''
    except ValueError:
        magic = b''
    if len(magic) >= total:
        return magic[:total]
    pad = _random_pad(total - len(magic), charset)
    # prepend: magic first, then random fill
    # append : random fill, then magic last
    return (magic + pad) if is_prepend else (pad + magic)


def build_payload(row: HostedFile, db) -> tuple[bytes, str]:
    """Assemble the exact bytes a client should receive for this hosted file.

    Returns (final_bytes, content_type). Raises FileNotFoundError if the
    on-disk payload is missing.
    """
    disk = Path(row.disk_path)
    if not disk.exists():
        raise FileNotFoundError(row.disk_path)

    raw = disk.read_bytes()

    # Apply transform pipeline
    if row.transform:
        from app.transforms import apply_transforms
        try:
            raw = apply_transforms(raw, row.transform, xor_key=row.xor_key or 0x41)
        except ValueError:
            pass  # serve raw on invalid pipeline

    # Apply prepend / append padding (with optional magic bytes from content-type preset)
    preset = db.query(ContentTypePreset).filter(
        ContentTypePreset.content_type == row.content_type
    ).first()
    cs = preset.random_charset if preset else 'binary'

    if row.prepend_bytes and row.prepend_bytes > 0:
        magic_pre = preset.magic_prepend if preset else ''
        raw = _apply_magic(row.prepend_bytes, magic_pre, cs, is_prepend=True) + raw

    if row.append_bytes and row.append_bytes > 0:
        magic_app = preset.magic_append if preset else ''
        raw = raw + _apply_magic(row.append_bytes, magic_app, cs, is_prepend=False)

    return raw, row.content_type
