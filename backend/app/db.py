from __future__ import annotations

import os
from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String, DateTime, BigInteger, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

DB_PATH = Path(os.environ.get('DATA_DIR', '/data')) / 'payload-server.db'
engine = create_engine(f'sqlite:///{DB_PATH}', connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class HostedFile(Base):
    __tablename__ = 'hosted_files'
    id            = Column(Integer, primary_key=True)
    uri           = Column(String, unique=True, nullable=False, index=True)
    filename      = Column(String, nullable=False)          # original filename
    content_type  = Column(String, default='application/octet-stream')
    prepend_bytes = Column(Integer, default=0)
    file_size     = Column(BigInteger, default=0)           # raw payload size
    disk_path     = Column(String, nullable=False)          # path on disk
    append_bytes  = Column(Integer, default=0)             # random bytes appended after payload
    dl_filename   = Column(String, nullable=True)           # Content-Disposition filename
    transform     = Column(String, nullable=True)           # e.g. 'xor,base64'
    xor_key       = Column(Integer, default=0x41)           # XOR key (0-255)
    downloads     = Column(Integer, default=0)
    last_download = Column(DateTime, nullable=True)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    note          = Column(String, nullable=True)           # free-text label


class DownloadLog(Base):
    """One row per file download."""
    __tablename__ = 'download_logs'
    id            = Column(Integer, primary_key=True)
    file_id       = Column(Integer, nullable=False, index=True)   # HostedFile.id (may be deleted)
    uri           = Column(String, nullable=False, index=True)
    remote_ip     = Column(String, nullable=True)
    user_agent    = Column(String, nullable=True)
    bytes_served  = Column(BigInteger, default=0)                 # total bytes after transforms + padding
    ts            = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class ContentTypePreset(Base):
    """Magic bytes preset for a given Content-Type.

    magic_prepend / magic_append : hex string (e.g. 'FFD8FFE0'), stored uppercase.
    random_charset : 'binary' | 'printable' | 'alphanum'
      - binary    : os.urandom (any byte)
      - printable : random printable ASCII (0x20-0x7e)
      - alphanum  : [A-Za-z0-9]
    """
    __tablename__ = 'content_type_presets'
    id             = Column(Integer, primary_key=True)
    content_type   = Column(String, unique=True, nullable=False, index=True)
    magic_prepend  = Column(Text, default='')   # hex, applied as prefix of prepend window
    magic_append   = Column(Text, default='')   # hex, applied as suffix of append window
    random_charset = Column(String, default='binary')  # binary | printable | alphanum
    note           = Column(String, nullable=True)


DEFAULT_PRESETS = [
    {'content_type': 'image/jpeg',        'magic_prepend': 'FFD8FFE000104A464946000101',       'magic_append': 'FFD9',     'random_charset': 'binary'},
    {'content_type': 'image/png',         'magic_prepend': '89504E470D0A1A0A',                 'magic_append': '0000000049454E44AE426082', 'random_charset': 'binary'},
    {'content_type': 'image/gif',         'magic_prepend': '474946383961',                     'magic_append': '3B',       'random_charset': 'binary'},
    {'content_type': 'application/pdf',   'magic_prepend': '255044462D312E340A',               'magic_append': '0A2525454F460A', 'random_charset': 'binary'},
    {'content_type': 'application/zip',   'magic_prepend': '504B0304',                         'magic_append': '504B0506', 'random_charset': 'binary'},
    {'content_type': 'application/javascript', 'magic_prepend': '2F2A2120',                     'magic_append': '0A7D28293B0A', 'random_charset': 'printable', 'note': '/*! ... }());'},
    {'content_type': 'text/html',         'magic_prepend': '3C21444F43545950452068746D6C3E0A3C68746D6C206C616E673D22656E223E0A3C686561643E0A3C6D65746120636861727365743D225554462D38223E0A', 'magic_append': '0A3C2F626F64793E0A3C2F68746D6C3E0A', 'random_charset': 'printable', 'note': '<!DOCTYPE html>...</html>'},
    {'content_type': 'text/plain',        'magic_prepend': '',                                 'magic_append': '',         'random_charset': 'printable'},
]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    # Seed default presets if table is empty
    db = SessionLocal()
    try:
        if db.query(ContentTypePreset).count() == 0:
            for p in DEFAULT_PRESETS:
                db.add(ContentTypePreset(**p))
            db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
