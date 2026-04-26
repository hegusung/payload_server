"""Public serving API — no auth."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.db import DownloadLog, HostedFile, ContentTypePreset, SessionLocal

BODY_404 = os.environ.get(
    'BODY_404',
    '<!DOCTYPE html><html><head><title>404</title></head><body>Not Found</body></html>',
).encode()

router = APIRouter()


@router.get('/{path:path}')
async def serve_file(path: str, request: Request):
    uri = '/' + path.lstrip('/')

    db = SessionLocal()
    try:
        row = db.query(HostedFile).filter(HostedFile.uri == uri).first()
        if not row:
            return Response(
                content=BODY_404,
                status_code=200,   # 200 intentional — avoid fingerprinting
                media_type='text/html',
                headers={'Server': 'nginx/1.24.0'},
            )

        disk = Path(row.disk_path)
        if not disk.exists():
            return Response(content=BODY_404, status_code=200, media_type='text/html',
                            headers={'Server': 'nginx/1.24.0'})

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

        def _random_pad(n: int, charset: str) -> bytes:
            if n <= 0:
                return b''
            if charset == 'alphanum':
                import random, string
                return bytes(random.choices(string.ascii_letters + string.digits, k=n), 'ascii')
            elif charset == 'printable':
                import random, string
                return bytes(random.choices(string.printable[:94], k=n), 'ascii')
            else:
                return os.urandom(n)

        def _apply_magic(total: int, magic_hex: str, charset: str, is_prepend: bool) -> bytes:
            """Build a padding block of `total` bytes using magic as anchor."""
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
            if is_prepend:
                return magic + pad
            else:
                return pad + magic

        cs = preset.random_charset if preset else 'binary'

        if row.prepend_bytes and row.prepend_bytes > 0:
            magic_pre = preset.magic_prepend if preset else ''
            raw = _apply_magic(row.prepend_bytes, magic_pre, cs, is_prepend=True) + raw

        if row.append_bytes and row.append_bytes > 0:
            magic_app = preset.magic_append if preset else ''
            raw = raw + _apply_magic(row.append_bytes, magic_app, cs, is_prepend=False)

        # Track download
        row.downloads     += 1
        row.last_download  = datetime.now(timezone.utc)

        # Detailed download log
        remote_ip  = request.headers.get('X-Forwarded-For', request.client.host if request.client else None)
        user_agent = request.headers.get('User-Agent')
        db.add(DownloadLog(
            file_id=row.id,
            uri=row.uri,
            remote_ip=remote_ip,
            user_agent=user_agent,
            bytes_served=len(raw),
        ))
        db.commit()

        headers = {
            'Server': 'nginx/1.24.0',
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
        }
        if row.dl_filename:
            headers['Content-Disposition'] = f'inline; filename="{row.dl_filename}"'

        return Response(
            content=raw,
            status_code=200,
            media_type=row.content_type,
            headers=headers,
        )
    finally:
        db.close()
