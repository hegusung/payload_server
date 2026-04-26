"""
payload-server — dual-port file hosting server
Management port (MGMT_PORT): REST API + UI, token-protected
Serving port (SERVE_PORT):   Public file serving, no auth
"""
from __future__ import annotations

import os
import uvicorn
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.db import init_db
from app.api.mgmt import router as mgmt_router
from app.api.serve import router as serve_router

MGMT_PORT  = int(os.environ.get('MGMT_PORT', 8080))
SERVE_PORT = int(os.environ.get('SERVE_PORT', 8443))
DATA_DIR   = Path(os.environ.get('DATA_DIR', '/data'))

# ── Management app ─────────────────────────────────────────────────────────────
mgmt_app = FastAPI(title='payload-server management', docs_url=None, redoc_url=None)
mgmt_app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
mgmt_app.include_router(mgmt_router, prefix='/api')

static_dir = Path(__file__).parent.parent / 'dist'
if static_dir.exists():
    mgmt_app.mount('/', StaticFiles(directory=str(static_dir), html=True), name='static')

# ── Serving app ────────────────────────────────────────────────────────────────
serve_app = FastAPI(title='payload-server serve', docs_url=None, redoc_url=None)
serve_app.include_router(serve_router)


@mgmt_app.on_event('startup')
async def startup():
    init_db()
    DATA_DIR.mkdir(parents=True, exist_ok=True)


async def _run_server(app, port, **kwargs):
    config = uvicorn.Config(app, host='0.0.0.0', port=port, server_header=False, **kwargs)
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    init_db()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    ssl_keyfile  = os.environ.get('SSL_KEY')
    ssl_certfile = os.environ.get('SSL_CERT')
    use_ssl = bool(ssl_keyfile and ssl_certfile and
                   Path(ssl_keyfile).exists() and Path(ssl_certfile).exists())

    serve_kwargs = {}
    if use_ssl:
        serve_kwargs['ssl_keyfile']  = ssl_keyfile
        serve_kwargs['ssl_certfile'] = ssl_certfile

    await asyncio.gather(
        _run_server(mgmt_app, MGMT_PORT),
        _run_server(serve_app, SERVE_PORT, **serve_kwargs),
    )


if __name__ == '__main__':
    asyncio.run(main())
