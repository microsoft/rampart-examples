# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""AuthProxy aiohttp server and request logging."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol, Self, cast, runtime_checkable

import aiohttp
import aiohttp.log
from aiohttp import web

if TYPE_CHECKING:
    from openclaw.auth.routes import ProviderRoute

logger = logging.getLogger("auth_proxy")

# Hop-by-hop headers that must not be forwarded.
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    }
)


@runtime_checkable
class RequestLogger(Protocol):
    """Optional hook for structured logging / RAMPART integration."""

    async def log_request_async(
        self,
        *,
        route: ProviderRoute,
        method: str,
        target_url: str,
        status: int,
        duration_ms: float,
        request_body: bytes | None = None,
        response_body: bytes | None = None,
    ) -> None: ...


class JsonlRequestLogger:
    """Appends one JSON line per request to a log file."""

    def __init__(self, *, path: str = "proxy_requests.jsonl") -> None:
        self._path = path
        self._file: Any = None
        self._lock = asyncio.Lock()

    def _ensure_file(self) -> Any:
        if self._file is None or self._file.closed:
            self._file = open(self._path, "a", encoding="utf-8")
        return self._file

    async def log_request_async(self, **kwargs: Any) -> None:
        record = {
            "ts": time.time(),
            "provider": kwargs["route"].name,
            "method": kwargs["method"],
            "url": kwargs["target_url"],
            "status": kwargs["status"],
            "duration_ms": round(kwargs["duration_ms"], 2),
        }
        line = json.dumps(record) + "\n"
        async with self._lock:
            loop = asyncio.get_running_loop()
            f = self._ensure_file()
            await loop.run_in_executor(None, f.write, line)
            await loop.run_in_executor(None, f.flush)

    async def close_async(self) -> None:
        if self._file and not self._file.closed:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._file.close)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close_async()


class AuthProxy:
    """Async reverse proxy with per-route auth injection and SSE streaming."""

    def __init__(
        self,
        *,
        routes: list[ProviderRoute],
        host: str = "127.0.0.1",
        port: int = 12435,
        request_logger: RequestLogger | None = None,
        log_bodies: bool = False,
    ) -> None:
        self._routes = sorted(routes, key=lambda r: len(r.path_prefix), reverse=True)
        self._host = host
        self._port = port
        self._request_logger = request_logger
        self._log_bodies = log_bodies
        self._session: aiohttp.ClientSession | None = None

    def _match_route(self, path: str) -> tuple[ProviderRoute, str] | None:
        for route in self._routes:
            if path == route.path_prefix or path.startswith(route.path_prefix + "/"):
                remainder = path[len(route.path_prefix) :]
                return route, remainder
        return None

    async def _get_session_async(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=300, connect=10),
                auto_decompress=False,
            )
        return self._session

    async def _handle_request_async(self, request: web.Request) -> web.StreamResponse:
        match = self._match_route(request.path)
        if match is None:
            routes_info = {r.path_prefix: r.name for r in self._routes}
            return web.json_response(
                {"error": "no matching route", "available_routes": routes_info},
                status=404,
            )

        route, target_path = match
        query_string = request.query_string
        target_url = route.target_base_url.rstrip("/") + target_path
        if query_string:
            target_url += f"?{query_string}"

        # Build forwarded headers — strip hop-by-hop.
        fwd_headers: dict[str, str] = {
            k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP
        }

        # Inject auth.
        try:
            result = route.auth(fwd_headers, request.method, target_url)
            if inspect.isawaitable(result):
                fwd_headers = cast("dict[str, str]", await result)
            else:
                fwd_headers = result
        except Exception as exc:
            logger.exception("Auth injection failed for %s: %s", route.name, exc)
            return web.json_response({"error": "proxy_error"}, status=502)

        fwd_headers.update(route.extra_headers)

        body = await request.read() if request.can_read_body else None
        t0 = time.monotonic()

        session = await self._get_session_async()
        try:
            async with session.request(
                request.method,
                target_url,
                headers=fwd_headers,
                data=body,
                allow_redirects=False,
            ) as upstream_resp:
                duration_ms = (time.monotonic() - t0) * 1000

                resp_headers = {
                    k: v for k, v in upstream_resp.headers.items() if k.lower() not in _HOP_BY_HOP
                }

                logger.info(
                    "%s %s -> %s %s [%dms]",
                    request.method,
                    route.name,
                    upstream_resp.status,
                    target_path,
                    int(duration_ms),
                )

                response = web.StreamResponse(status=upstream_resp.status, headers=resp_headers)
                await response.prepare(request)

                collected_body = bytearray() if self._log_bodies else None
                async for chunk, _ in upstream_resp.content.iter_chunks():
                    await response.write(chunk)
                    if collected_body is not None:
                        collected_body.extend(chunk)

                await response.write_eof()

                if self._request_logger:
                    try:
                        await self._request_logger.log_request_async(
                            route=route,
                            method=request.method,
                            target_url=target_url,
                            status=upstream_resp.status,
                            duration_ms=duration_ms,
                            request_body=body if self._log_bodies else None,
                            response_body=(
                                bytes(collected_body) if collected_body is not None else None
                            ),
                        )
                    except Exception:
                        logger.exception("Request logger failed")

                return response

        except aiohttp.ClientError as exc:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.exception(
                "%s %s -> ERROR %s [%dms]",
                request.method,
                route.name,
                exc,
                int(duration_ms),
            )
            return web.json_response({"error": "upstream_error"}, status=502)

    async def _health_async(self, _request: web.Request) -> web.Response:
        routes = [
            {"name": r.name, "prefix": r.path_prefix, "target": r.target_base_url}
            for r in self._routes
        ]
        return web.json_response({"status": "ok", "routes": routes})

    async def _on_shutdown_async(self, _app: web.Application) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        close_async = getattr(self._request_logger, "close_async", None)
        if close_async is not None:
            await close_async()

    def run(self) -> None:
        app = web.Application()
        app.on_shutdown.append(self._on_shutdown_async)
        app.router.add_route("GET", "/health", self._health_async)
        app.router.add_route("*", "/{path:.*}", self._handle_request_async)

        logger.info("Auth proxy starting on %s:%d", self._host, self._port)
        for route in self._routes:
            logger.info(
                "  %s -> %s (%s)",
                route.path_prefix,
                route.target_base_url,
                route.name,
            )
        web.run_app(app, host=self._host, port=self._port, print=None)
