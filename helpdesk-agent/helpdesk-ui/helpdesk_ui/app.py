# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""FastAPI application factory + ``helpdesk-ui`` console entrypoint."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from helpdesk_ui.routes import api_router

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


_HELPDESK_AGENT_DIR = Path(__file__).resolve().parents[2]
_DOTENV_PATH = _HELPDESK_AGENT_DIR / ".env"

# --- Static bundle resolution -------------------------------------------

_DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def _resolve_static_dir() -> Path:
    override = os.getenv("HELPDESK_UI_STATIC_DIR")
    return Path(override).resolve() if override else _DEFAULT_STATIC_DIR


# --- Middleware --------------------------------------------------------

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),
}

_MAX_BODY_BYTES = 256 * 1024


# --- App factory -------------------------------------------------------


def create_app() -> FastAPI:
    """Build the FastAPI app.

    Args:
        agent_factory: optional callable returning a fresh agent per
            chat turn. Defaults to ``helpdesk_agent.agent.build_agent``.
            Tests pass a fake to avoid needing an LLM provider.
    """
    app = FastAPI(title="HelpdeskAgent")

    @app.middleware("http")
    async def _max_body(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        cl = request.headers.get("content-length")
        if cl is not None and cl.isdigit() and int(cl) > _MAX_BODY_BYTES:
            return Response(status_code=413, content="Payload too large")
        return await call_next(request)

    @app.middleware("http")
    async def _security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    app.include_router(api_router)

    static_dir = _resolve_static_dir()
    index_path = static_dir / "index.html"
    assets_dir = static_dir / "assets"

    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(index_path)

    return app


def run() -> None:
    """Console entrypoint: ``helpdesk-ui``."""
    load_dotenv(_DOTENV_PATH if _DOTENV_PATH.exists() else None)

    uvicorn.run(
        "helpdesk_ui.app:create_app",
        factory=True,
        host=os.getenv("HELPDESK_WEB_HOST", "127.0.0.1"),
        port=int(os.getenv("HELPDESK_WEB_PORT", "8000")),
    )
