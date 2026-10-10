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
from app.db import (ContentTypePreset, Deployment, DeliveryTarget, DownloadLog,
                    HostedFile, get_db)

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


# ── Delivery providers & targets ─────────────────────────────────────────────

from fastapi import BackgroundTasks  # noqa: E402

from app.crypto import decrypt_config, encrypt_config  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.providers import REGISTRY, get_provider, list_providers  # noqa: E402


def _redact_config(provider_key: str, config: dict) -> dict:
    """Return config with secret fields masked for display."""
    cls = REGISTRY.get(provider_key)
    secret_keys = {f.key for f in cls.config_fields if f.secret} if cls else set()
    out = {}
    for k, v in config.items():
        if k in secret_keys:
            out[k] = '••••••••' if v else ''
        else:
            out[k] = v
    return out


def _target_view(t: DeliveryTarget) -> dict:
    cfg = decrypt_config(t.config_enc)
    return {
        'id': t.id,
        'name': t.name,
        'provider_key': t.provider_key,
        'config': _redact_config(t.provider_key, cfg),
        'note': t.note,
        'created_at': t.created_at.isoformat() if t.created_at else None,
    }


def _deployment_view(d: Deployment) -> dict:
    return {
        'id': d.id,
        'file_id': d.file_id,
        'target_id': d.target_id,
        'uri': d.uri,
        'status': d.status,
        'public_url': d.public_url,
        'provider_ref': d.provider_ref,
        'bytes_pushed': d.bytes_pushed,
        'error': d.error,
        'synced_at': d.synced_at.isoformat() if d.synced_at else None,
        'created_at': d.created_at.isoformat() if d.created_at else None,
    }


@router.get('/providers', dependencies=[Depends(require_token)])
def get_providers():
    return list_providers()


class TargetIn(BaseModel):
    name: str
    provider_key: str
    config: dict
    note: str | None = None


@router.get('/targets', dependencies=[Depends(require_token)])
def list_targets(db: Session = Depends(get_db)):
    rows = db.query(DeliveryTarget).order_by(DeliveryTarget.created_at.desc()).all()
    return [_target_view(t) for t in rows]


@router.post('/targets', dependencies=[Depends(require_token)])
def create_target(body: TargetIn, db: Session = Depends(get_db)):
    if body.provider_key not in REGISTRY:
        raise HTTPException(status_code=400, detail=f'Unknown provider: {body.provider_key}')
    if db.query(DeliveryTarget).filter(DeliveryTarget.name == body.name).first():
        raise HTTPException(status_code=409, detail='A target with this name already exists')
    try:
        get_provider(body.provider_key, body.config).provision()
    except Exception as e:
        resource = 'Container' if body.provider_key == 'azure' else 'Bucket'
        raise HTTPException(status_code=502, detail=f'{resource} creation failed: {e}')
    row = DeliveryTarget(
        name=body.name,
        provider_key=body.provider_key,
        config_enc=encrypt_config(body.config),
        note=body.note or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _target_view(row)


@router.put('/targets/{target_id}', dependencies=[Depends(require_token)])
def update_target(target_id: int, body: TargetIn, db: Session = Depends(get_db)):
    row = db.get(DeliveryTarget, target_id)
    if not row:
        raise HTTPException(status_code=404, detail='Target not found')
    if body.provider_key not in REGISTRY:
        raise HTTPException(status_code=400, detail=f'Unknown provider: {body.provider_key}')
    # Preserve existing secret values when the UI sends back the masked placeholder.
    existing = decrypt_config(row.config_enc)
    cls = REGISTRY[body.provider_key]
    secret_keys = {f.key for f in cls.config_fields if f.secret}
    merged = dict(body.config)
    for k in secret_keys:
        if merged.get(k) in ('', '••••••••', None) and existing.get(k):
            merged[k] = existing[k]
    try:
        get_provider(body.provider_key, merged).provision()
    except Exception as e:
        resource = 'Container' if body.provider_key == 'azure' else 'Bucket'
        raise HTTPException(status_code=502, detail=f'{resource} creation failed: {e}')
    row.name = body.name
    row.provider_key = body.provider_key
    row.config_enc = encrypt_config(merged)
    row.note = body.note or None
    db.commit()
    return _target_view(row)


@router.delete('/targets/{target_id}', dependencies=[Depends(require_token)])
def delete_target(target_id: int, delete_bucket: bool = False, db: Session = Depends(get_db),
                  delete_container: bool = False):
    row = db.get(DeliveryTarget, target_id)
    if not row:
        raise HTTPException(status_code=404, detail='Target not found')
    if delete_bucket or delete_container:
        resource = 'Container' if delete_container else 'Bucket'
        if (delete_bucket and row.provider_key not in ('s3', 'r2')) or (delete_container and row.provider_key != 'azure'):
            raise HTTPException(status_code=400, detail=f'This target does not support {resource.lower()} deletion')
        if db.query(Deployment).filter(Deployment.target_id == target_id,
                                       Deployment.status == 'pending').first():
            raise HTTPException(status_code=409, detail=f'Wait for pending deployments before deleting the {resource.lower()}')
        from botocore.exceptions import ClientError
        try:
            provider = get_provider(row.provider_key, decrypt_config(row.config_enc))
            if delete_container:
                provider.delete_container()
            else:
                provider.delete_bucket()
        except ClientError as e:
            if e.response.get('Error', {}).get('Code') == 'BucketNotEmpty':
                raise HTTPException(status_code=409, detail='Bucket is not empty. Remove its objects and versions first.')
            raise HTTPException(status_code=502, detail=f'Bucket deletion failed: {e}')
        except Exception as e:
            status = 409 if isinstance(e, ValueError) else 502
            raise HTTPException(status_code=status, detail=f'{resource} deletion failed: {e}')
    db.query(Deployment).filter(Deployment.target_id == target_id).delete()
    db.delete(row)
    db.commit()
    return {'ok': True}


@router.post('/targets/{target_id}/health', dependencies=[Depends(require_token)])
def target_health(target_id: int, db: Session = Depends(get_db)):
    row = db.get(DeliveryTarget, target_id)
    if not row:
        raise HTTPException(status_code=404, detail='Target not found')
    cfg = decrypt_config(row.config_enc)
    try:
        provider = get_provider(row.provider_key, cfg)
        ok, msg = provider.health()
    except Exception as e:  # noqa: BLE001
        ok, msg = False, str(e)
    return {'ok': ok, 'message': msg}


# ── Deployments ──────────────────────────────────────────────────────────────

@router.get('/targets/{target_id}/files', dependencies=[Depends(require_token)])
def target_files(target_id: int, db: Session = Depends(get_db)):
    target = db.get(DeliveryTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail='Target not found')
    config = decrypt_config(target.config_enc)
    try:
        files = get_provider(target.provider_key, config).list_files()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'Could not list remote files: {e}')
    return {'files': files, 'prefix': (config.get('prefix') or '').lstrip('/')}


class RemoteFilesDeleteIn(BaseModel):
    refs: list[str]


@router.post('/targets/{target_id}/files/delete', dependencies=[Depends(require_token)])
def delete_target_files(target_id: int, body: RemoteFilesDeleteIn, db: Session = Depends(get_db)):
    target = db.get(DeliveryTarget, target_id)
    if not target:
        raise HTTPException(status_code=404, detail='Target not found')
    config = decrypt_config(target.config_enc)
    prefix = (config.get('prefix') or '').lstrip('/')
    refs = list(dict.fromkeys(body.refs))
    if not refs or any(not ref or not ref.startswith(prefix) for ref in refs):
        raise HTTPException(status_code=400, detail='Select files within this target’s configured prefix')
    if db.query(Deployment).filter(Deployment.target_id == target_id, Deployment.status == 'pending').first():
        raise HTTPException(status_code=409, detail='Wait for pending deployments before deleting remote files')
    provider = get_provider(target.provider_key, config)
    deleted, errors = [], []
    for ref in refs:
        try:
            provider.delete(ref)
        except Exception as e:
            errors.append({'ref': ref, 'message': str(e)})
            continue
        db.query(Deployment).filter(Deployment.target_id == target_id, Deployment.provider_ref == ref).delete()
        db.commit()
        deleted.append(ref)
    return {'deleted': deleted, 'errors': errors}

@router.get('/deployments', dependencies=[Depends(require_token)])
def list_deployments(file_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(Deployment).order_by(Deployment.created_at.desc())
    if file_id is not None:
        q = q.filter(Deployment.file_id == file_id)
    return [_deployment_view(d) for d in q.all()]


def _run_deploy(deployment_id: int):
    """Background worker: assemble payload and push to the target. Own DB session."""
    from app.payload import build_payload
    db = SessionLocal()
    try:
        dep = db.get(Deployment, deployment_id)
        if not dep:
            return
        file_row = db.get(HostedFile, dep.file_id)
        target = db.get(DeliveryTarget, dep.target_id)
        if not file_row or not target:
            dep.status = 'error'
            dep.error = 'file or target no longer exists'
            db.commit()
            return
        try:
            data, content_type = build_payload(file_row, db)
            provider = get_provider(target.provider_key, decrypt_config(target.config_enc))
            result = provider.deploy(
                file_row.uri, data, content_type,
                meta={'dl_filename': file_row.dl_filename, 'note': file_row.note},
            )
            dep.status = 'deployed'
            dep.public_url = result.public_url
            dep.provider_ref = result.ref
            dep.bytes_pushed = len(data)
            dep.error = None
            dep.synced_at = datetime.now(timezone.utc)
        except Exception as e:  # noqa: BLE001 — record failure for the UI
            dep.status = 'error'
            dep.error = str(e)
        db.commit()
    finally:
        db.close()


class DeployIn(BaseModel):
    target_id: int


@router.post('/files/{file_id}/deploy', dependencies=[Depends(require_token)])
def deploy_file(file_id: int, body: DeployIn, background: BackgroundTasks,
                db: Session = Depends(get_db)):
    file_row = db.get(HostedFile, file_id)
    if not file_row:
        raise HTTPException(status_code=404, detail='File not found')
    target = db.get(DeliveryTarget, body.target_id)
    if not target:
        raise HTTPException(status_code=404, detail='Target not found')
    # One deployment row per (file, target): reuse if present.
    dep = (db.query(Deployment)
             .filter(Deployment.file_id == file_id, Deployment.target_id == body.target_id)
             .first())
    if not dep:
        dep = Deployment(file_id=file_id, target_id=body.target_id, uri=file_row.uri)
        db.add(dep)
    dep.uri = file_row.uri
    dep.status = 'pending'
    dep.error = None
    db.commit()
    db.refresh(dep)
    background.add_task(_run_deploy, dep.id)
    return _deployment_view(dep)


@router.delete('/deployments/{deployment_id}', dependencies=[Depends(require_token)])
def delete_deployment(deployment_id: int, remote: bool = True, db: Session = Depends(get_db)):
    dep = db.get(Deployment, deployment_id)
    if not dep:
        raise HTTPException(status_code=404, detail='Deployment not found')
    if remote and dep.provider_ref:
        target = db.get(DeliveryTarget, dep.target_id)
        if target:
            try:
                provider = get_provider(target.provider_key, decrypt_config(target.config_enc))
                provider.delete(dep.provider_ref)
            except Exception as e:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f'Remote delete failed: {e}')
    db.delete(dep)
    db.commit()
    return {'ok': True}
