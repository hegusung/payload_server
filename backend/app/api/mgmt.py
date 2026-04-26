"""Management API — token-protected."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_token
from app.db import ContentTypePreset, DownloadLog, HostedFile, get_db

DATA_DIR = Path(os.environ.get('DATA_DIR', '/data')) / 'files'
router = APIRouter()


def _safe_uri(uri: str) -> str:
    uri = uri.strip()
    if not uri.startswith('/'):
        uri = '/' + uri
    # Sanitize — allow only safe path chars
    uri = re.sub(r'[^a-zA-Z0-9/_.\-]', '_', uri)
    return uri


def _disk_path(uri: str) -> Path:
    # Flatten URI to a safe filename using sha256 prefix + sanitized name
    h = hashlib.sha256(uri.encode()).hexdigest()[:12]
    safe = re.sub(r'[^a-zA-Z0-9._\-]', '_', uri.lstrip('/'))
    return DATA_DIR / f'{h}_{safe}'


class FileInfo(BaseModel):
    id: int
    uri: str
    filename: str
    content_type: str
    prepend_bytes: int
    append_bytes: int
    dl_filename: str | None
    transform: str | None
    xor_key: int
    file_size: int
    downloads: int
    last_download: datetime | None
    created_at: datetime
    note: str | None

    class Config:
        from_attributes = True


@router.get('/files', response_model=list[FileInfo], dependencies=[Depends(require_token)])
def list_files(db: Session = Depends(get_db)):
    return db.query(HostedFile).order_by(HostedFile.created_at.desc()).all()


@router.post('/files', response_model=FileInfo, dependencies=[Depends(require_token)])
async def upload_file(
    uri: str = Form(...),
    content_type: str = Form('application/octet-stream'),
    prepend_bytes: int = Form(0),
    append_bytes: int = Form(0),
    dl_filename: str = Form(''),
    transform: str = Form(''),
    xor_key: int = Form(0x41),
    note: str = Form(''),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    from app.transforms import apply_transforms, VALID_TRANSFORMS
    uri = _safe_uri(uri)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Validate transform pipeline
    if transform.strip():
        steps = [s.strip().lower() for s in transform.split(',') if s.strip()]
        unknown = [s for s in steps if s not in VALID_TRANSFORMS]
        if unknown:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=f'Unknown transforms: {", ".join(unknown)}')

    raw = await file.read()
    disk = _disk_path(uri)
    disk.write_bytes(raw)

    fields = dict(
        filename      = file.filename or uri.split('/')[-1],
        content_type  = content_type,
        prepend_bytes = prepend_bytes,
        append_bytes  = append_bytes,
        dl_filename   = dl_filename.strip() or None,
        transform     = transform.strip() or None,
        xor_key       = xor_key & 0xFF,
        file_size     = len(raw),
        disk_path     = str(disk),
        note          = note or None,
    )

    existing = db.query(HostedFile).filter(HostedFile.uri == uri).first()
    if existing:
        old = Path(existing.disk_path)
        if old.exists() and str(old) != str(disk):
            old.unlink(missing_ok=True)
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.downloads     = 0
        existing.last_download = None
        existing.created_at    = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return existing

    row = HostedFile(uri=uri, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete('/files/{file_id}', dependencies=[Depends(require_token)])
def delete_file(file_id: int, db: Session = Depends(get_db)):
    row = db.get(HostedFile, file_id)
    if not row:
        raise HTTPException(status_code=404, detail='File not found')
    Path(row.disk_path).unlink(missing_ok=True)
    db.delete(row)
    db.commit()
    return {'ok': True}


@router.get('/health')
def health():
    return {'status': 'ok'}


# ── Download Logs ─────────────────────────────────────────────────────────

@router.get('/logs', dependencies=[Depends(require_token)])
def list_logs(
    uri: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(DownloadLog).order_by(DownloadLog.ts.desc())
    if uri:
        q = q.filter(DownloadLog.uri == uri)
    total = q.count()
    rows = q.offset(offset).limit(limit).all()
    return {
        'total': total,
        'logs': [{
            'id': r.id,
            'file_id': r.file_id,
            'uri': r.uri,
            'remote_ip': r.remote_ip,
            'user_agent': r.user_agent,
            'bytes_served': r.bytes_served,
            'ts': r.ts.isoformat() if r.ts else None,
        } for r in rows],
    }


@router.delete('/logs', dependencies=[Depends(require_token)])
def clear_logs(uri: str | None = None, db: Session = Depends(get_db)):
    q = db.query(DownloadLog)
    if uri:
        q = q.filter(DownloadLog.uri == uri)
    deleted = q.delete()
    db.commit()
    return {'deleted': deleted}


# ── Content-Type Presets ────────────────────────────────────────────────────

class PresetIn(BaseModel):
    content_type: str
    magic_prepend: str = ''
    magic_append: str = ''
    random_charset: str = 'binary'
    note: str | None = None


@router.get('/presets', dependencies=[Depends(require_token)])
def list_presets(db: Session = Depends(get_db)):
    rows = db.query(ContentTypePreset).order_by(ContentTypePreset.content_type).all()
    return [{'id': r.id, 'content_type': r.content_type, 'magic_prepend': r.magic_prepend,
             'magic_append': r.magic_append, 'random_charset': r.random_charset,
             'note': r.note} for r in rows]


@router.post('/presets', dependencies=[Depends(require_token)])
def create_preset(body: PresetIn, db: Session = Depends(get_db)):
    if db.query(ContentTypePreset).filter(ContentTypePreset.content_type == body.content_type).first():
        raise HTTPException(status_code=409, detail='Preset already exists for this content-type')
    # Validate hex fields
    for field, val in [('magic_prepend', body.magic_prepend), ('magic_append', body.magic_append)]:
        if val:
            try:
                bytes.fromhex(val)
            except ValueError:
                raise HTTPException(status_code=400, detail=f'{field} must be a valid hex string')
    if body.random_charset not in ('binary', 'printable', 'alphanum'):
        raise HTTPException(status_code=400, detail='random_charset must be binary, printable, or alphanum')
    row = ContentTypePreset(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {'id': row.id, 'content_type': row.content_type}


@router.put('/presets/{preset_id}', dependencies=[Depends(require_token)])
def update_preset(preset_id: int, body: PresetIn, db: Session = Depends(get_db)):
    row = db.query(ContentTypePreset).filter(ContentTypePreset.id == preset_id).first()
    if not row:
        raise HTTPException(status_code=404, detail='Preset not found')
    for field, val in [('magic_prepend', body.magic_prepend), ('magic_append', body.magic_append)]:
        if val:
            try:
                bytes.fromhex(val)
            except ValueError:
                raise HTTPException(status_code=400, detail=f'{field} must be a valid hex string')
    if body.random_charset not in ('binary', 'printable', 'alphanum'):
        raise HTTPException(status_code=400, detail='random_charset must be binary, printable, or alphanum')
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    db.commit()
    return {'ok': True}


@router.delete('/presets/{preset_id}', dependencies=[Depends(require_token)])
def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    row = db.query(ContentTypePreset).filter(ContentTypePreset.id == preset_id).first()
    if not row:
        raise HTTPException(status_code=404, detail='Preset not found')
    db.delete(row)
    db.commit()
    return {'ok': True}
