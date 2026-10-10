"""
Delivery provider interface.

A provider takes the final assembled payload bytes (from app.payload.build_payload)
and stages them at an external destination, returning a public URL. Add a new
provider by subclassing DeliveryProvider and decorating it with @register.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeployResult:
    public_url: str                 # URL where the payload can be fetched
    ref: str                        # provider-specific handle used for later delete
    extra: dict = field(default_factory=dict)   # anything worth surfacing in the UI


@dataclass
class ConfigField:
    """Describes one configurable field, for the UI to render a form."""
    key: str
    label: str
    type: str = 'text'              # 'text' | 'password' | 'number' | 'bool'
    required: bool = True
    secret: bool = False            # redacted in API responses, encrypted at rest
    placeholder: str = ''
    help: str = ''


class DeliveryProvider:
    """Base class for all delivery providers.

    Subclasses set `key` / `label` / `config_fields` and implement deploy/delete.
    `config` is the decrypted dict of the configured target.
    """
    key: str = ''
    label: str = ''
    config_fields: list[ConfigField] = []

    def __init__(self, config: dict):
        self.config = config or {}

    # -- lifecycle -----------------------------------------------------------
    def provision(self) -> None:
        """Create destination resources if needed. Default: no resources to create."""

    def deploy(self, uri: str, data: bytes, content_type: str, meta: dict) -> DeployResult:
        raise NotImplementedError

    def delete(self, ref: str) -> None:
        raise NotImplementedError

    def list_files(self) -> list[dict]:
        """List current remote objects within the configured prefix."""
        raise NotImplementedError

    def health(self) -> tuple[bool, str]:
        """Return (ok, message). Default: assume reachable."""
        return True, 'ok'

    # -- helpers -------------------------------------------------------------
    @classmethod
    def describe(cls) -> dict:
        return {
            'key': cls.key,
            'label': cls.label,
            'config_fields': [vars(f) for f in cls.config_fields],
        }
