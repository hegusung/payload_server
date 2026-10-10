"""Public serving API — no auth."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.db import DownloadLog, HostedFile, SessionLocal
from app.payload import build_payload

BODY_404 = os.environ.get(
    'BODY_404',
    '<!DOCTYPE html><html><head><title>404</title></head><body>Not Found</body></html>',
).encode()

router = APIRouter()


def _decoy_404() -> Response:
    return Response(
        content=BODY_404,
        status_code=200,   # 200 intentional — avoid fingerprinting
        media_type='text/html',
        headers={'Server': 'nginx/1.24.0'},
    )


@router.get('/{path:path}')
async def serve_file(path: str, request: Request):
    uri = '/' + path.lstrip('/')

    db = SessionLocal()
    try:
        row = db.query(HostedFile).filter(HostedFile.uri == uri).first()
        if not row:
            return _decoy_404()

        try:
            raw, content_type = build_payload(row, db)
        except FileNotFoundError:
            return _decoy_404()

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
            media_type=content_type,
            headers=headers,
        )
    finally:
        db.close()
