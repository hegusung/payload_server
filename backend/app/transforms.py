"""
Payload transform pipeline.
Usage: apply_transforms(data, 'xor,base64', xor_key=0x41)
Order: left to right, each transform receives the output of the previous.

Available transforms:
  xor       — XOR each byte with xor_key
  base64    — standard base64 encode
  base64u   — URL-safe base64, no padding
  netbios   — NetBIOS encode (nibbles → 'a'-'p')
  netbiosu  — NetBIOS encode uppercase ('A'-'P')
"""
from __future__ import annotations

import base64


def _xor(data: bytes, key: int) -> bytes:
    key = key & 0xFF
    return bytes(b ^ key for b in data)


def _base64_std(data: bytes) -> bytes:
    return base64.b64encode(data)


def _base64_url(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b'=')


def _netbios(data: bytes, upper: bool = False) -> bytes:
    base = ord('A') if upper else ord('a')
    out = bytearray()
    for byte in data:
        out.append(base + ((byte >> 4) & 0x0F))
        out.append(base + (byte & 0x0F))
    return bytes(out)


_TRANSFORMS: dict[str, callable] = {
    'xor':      None,       # handled separately (needs key)
    'base64':   _base64_std,
    'base64u':  _base64_url,
    'netbios':  lambda d: _netbios(d, upper=False),
    'netbiosu': lambda d: _netbios(d, upper=True),
}

VALID_TRANSFORMS = set(_TRANSFORMS.keys())


def apply_transforms(data: bytes, pipeline: str, xor_key: int = 0x41) -> bytes:
    """
    Apply a comma-separated list of transforms to data.
    Returns transformed bytes.
    Raises ValueError for unknown transform names.
    """
    if not pipeline or not pipeline.strip():
        return data

    steps = [s.strip().lower() for s in pipeline.split(',') if s.strip()]
    for step in steps:
        if step not in VALID_TRANSFORMS:
            raise ValueError(
                f'Unknown transform: "{step}". '
                f'Valid transforms: {", ".join(sorted(VALID_TRANSFORMS))}'
            )
        if step == 'xor':
            data = _xor(data, xor_key)
        else:
            data = _TRANSFORMS[step](data)
    return data
