"""Provider registry.

Usage:
    from app.providers import REGISTRY, get_provider, list_providers

Add a provider by importing its module below and decorating the class
with @register.
"""
from __future__ import annotations

from app.providers.base import DeliveryProvider

REGISTRY: dict[str, type[DeliveryProvider]] = {}


def register(cls: type[DeliveryProvider]) -> type[DeliveryProvider]:
    if not getattr(cls, 'key', ''):
        raise ValueError(f'{cls.__name__} must define a non-empty `key`')
    REGISTRY[cls.key] = cls
    return cls


def get_provider(key: str, config: dict) -> DeliveryProvider:
    if key not in REGISTRY:
        raise KeyError(f'Unknown provider: {key}')
    return REGISTRY[key](config)


def list_providers() -> list[dict]:
    return [cls.describe() for cls in REGISTRY.values()]


# Register built-in providers (import for side effects).
from app.providers import s3  # noqa: E402,F401
from app.providers import azure  # noqa: E402,F401
from app.providers import r2  # noqa: E402,F401
