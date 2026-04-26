from __future__ import annotations

import os
from fastapi import Header, HTTPException, status

MGMT_TOKEN = os.environ.get('MGMT_TOKEN', '')


def require_token(x_token: str = Header(..., alias='X-Token')):
    if not MGMT_TOKEN:
        raise HTTPException(status_code=500, detail='MGMT_TOKEN not configured')
    if x_token != MGMT_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid token')
    return x_token
