"""
Symmetric encryption for provider credentials stored at rest.

Key resolution order:
  1. SECRET_KEY env var (a urlsafe-base64 32-byte Fernet key, or any passphrase we hash)
  2. A key file auto-generated under DATA_DIR/.secret_key (persisted across restarts)

Credentials are never returned to the UI in plaintext — only a redacted view.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_DATA_DIR = Path(os.environ.get('DATA_DIR', '/data'))
_KEY_FILE = _DATA_DIR / '.secret_key'


def _derive_key(material: str) -> bytes:
    """Turn an arbitrary passphrase into a valid 32-byte urlsafe-base64 Fernet key."""
    digest = hashlib.sha256(material.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _load_key() -> bytes:
    env = os.environ.get('SECRET_KEY')
    if env:
        # Accept a ready-made Fernet key, else derive one from the passphrase.
        try:
            Fernet(env.encode())
            return env.encode()
        except (ValueError, TypeError):
            return _derive_key(env)
    # Fall back to a persisted auto-generated key.
    try:
        if _KEY_FILE.exists():
            return _KEY_FILE.read_bytes().strip()
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        _KEY_FILE.write_bytes(key)
        os.chmod(_KEY_FILE, 0o600)
        return key
    except OSError:
        # Last resort (e.g. read-only data dir): ephemeral key for this process.
        return Fernet.generate_key()


_fernet = Fernet(_load_key())


def encrypt_config(config: dict) -> str:
    """Encrypt a provider config dict -> opaque token string."""
    return _fernet.encrypt(json.dumps(config).encode()).decode()


def decrypt_config(token: str) -> dict:
    """Decrypt a token back into the config dict. Returns {} on failure."""
    if not token:
        return {}
    try:
        return json.loads(_fernet.decrypt(token.encode()).decode())
    except (InvalidToken, ValueError):
        return {}
