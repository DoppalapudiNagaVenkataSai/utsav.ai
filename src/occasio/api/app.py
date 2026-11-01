"""FastAPI application factory: middleware, error handling, routers, static UI."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from occasio import __version__
from occasio.ai.client import AIClient
from occasio.api import routes_ai, routes_plan
from occasio.api.limits import RateLimiter
from occasio.api.schemas import Health
from occasio.config import Settings, get_settings
from occasio.storage.repo import PlanRepository

log = logging.getLogger("occasio.api")

MAX_BODY_BYTES = 64 * 1024
AI_RATE_LIMIT = 20  # requests per window per IP
AI_RATE_WINDOW = 60.0
WEB_DIR = Path(__file__).resolve().parents[1] / "web"

# Same-origin only: no CORS middleware is installed, so browsers block cross-origin reads.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
# Swagger UI at /docs loads its assets from a CDN and uses an inline bootstrap script.
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "cross-origin-opener-policy": "same-origin",
}


class BodySizeLimit:
    """Reject request bodies over ``max_bytes`` with 413, even without Content-Length."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_bytes):
            await _too_large(scope, receive, send)
            return

        # Bodies are small (<= 64 KB), so buffer them and reject before the app sees any.
        chunks: list[bytes] = []
        size = 0
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":  # client disconnected
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_bytes:
                await _too_large(scope, receive, send)
                return
            chunks.append(chunk)
            more = message.get("more_body", False)

        body = b"".join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = JSONResponse({"detail": "Request body too large"}, status_code=413)
    await response(scope, receive, send)


def create_app(
    settings: Settings | None = None,
    ai: AIClient | None = None,
    repo: PlanRepository | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = FastAPI(
        title="Occasio",
        version=__version__,
        description="Event planning assistant: deterministic engine + Google Gemini layer.",
    )
    app.state.settings = settings
    app.state.ai = ai or AIClient.from_settings(settings)
    app.state.repo = repo or PlanRepository(settings.db_path)
    app.state.ai_limiter = RateLimiter(AI_RATE_LIMIT, AI_RATE_WINDOW)

    @app.middleware("http")
    async def headers_and_logging(request: Request, call_next: Any) -> Any:
        started = time.monotonic()
        response = await call_next(request)
        docs = request.url.path in ("/docs", "/redoc")
        response.headers["content-security-policy"] = DOCS_CSP if docs else CSP
        response.headers["x-req-path"] = request.url.path
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("cache-control", "no-store")
        # Method, route path (ids only), status and timing; never bodies or query text.
        log.info(
            "%s %s %s %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    @app.get("/healthz", tags=["meta"])
    def healthz() -> Health:
        enabled = app.state.ai.enabled
        return Health(ai_enabled=enabled, model=app.state.ai.model if enabled else None)

    app.include_router(routes_plan.router)
    app.include_router(routes_ai.router)
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True, check_dir=False), name="web")
    app.add_middleware(BodySizeLimit)
    return app
