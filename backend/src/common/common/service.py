from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text

from common.config import Settings
from common.database import create_engine, create_schema, create_session_factory
from common.errors import install_exception_handlers, request_trace_id
from common.event_publishers import build_event_publisher
from common.logging import configure_logging
from common.telemetry import metrics_response, setup_tracing

_MAX_HTTP_BODY_LOG_BYTES = 4096
_SKIP_HTTP_LOG_PATHS = {"/healthz", "/readyz", "/metrics"}
_OMIT_HTTP_REQUEST_BODY_PATHS = {
    "/alerts/alertmanager",
    "/api/v1/alerts/generic",
    "/api/v1/alerts/prometheus",
}
_MASKED_VALUE = "***"
_SENSITIVE_KEYS = {
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "access_token",
    "refresh_token",
    "jwt",
}


def _sanitize_url_credentials(val: str) -> str:
    if not isinstance(val, str) or "://" not in val:
        return val
    from urllib.parse import urlparse
    try:
        parsed = urlparse(val)
        if parsed.password:
            netloc = parsed.hostname or ""
            if parsed.username:
                netloc = f"{parsed.username}@{netloc}"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
    except Exception:
        pass
    return val


def _mask_sensitive_fields(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).strip().lower()
            if key_text in _SENSITIVE_KEYS:
                masked[key] = _MASKED_VALUE
            else:
                masked[key] = _mask_sensitive_fields(item)
        return masked
    if isinstance(value, list):
        return [_mask_sensitive_fields(item) for item in value]
    if isinstance(value, str):
        return _sanitize_url_credentials(value)
    return value


def _sanitize_http_payload(body: bytes, content_type: str | None) -> Any:
    if not body:
        return None
    if len(body) > _MAX_HTTP_BODY_LOG_BYTES:
        return f"<omitted: body size {len(body)} bytes exceeds {_MAX_HTTP_BODY_LOG_BYTES}>"

    lowered_type = (content_type or "").lower()
    if "application/json" in lowered_type:
        try:
            parsed = json.loads(body.decode("utf-8"))
            return _mask_sensitive_fields(parsed)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "<invalid-json-body>"

    if lowered_type.startswith("text/") or "application/x-www-form-urlencoded" in lowered_type:
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return "<non-utf8-text-body>"

    return f"<omitted: unsupported content-type {content_type or 'unknown'}>"


def create_app(
    *,
    title: str,
    settings: Settings,
    startup: Callable[[FastAPI], Awaitable[None]] | None = None,
    shutdown: Callable[[FastAPI], Awaitable[None]] | None = None,
) -> FastAPI:
    configure_logging(settings.service_name)
    logger = logging.getLogger(settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.producer = build_event_publisher(settings)
        try:
            await app.state.producer.start()
            if settings.database_enabled:
                app.state.db_engine = create_engine(settings)
                app.state.session_factory = create_session_factory(app.state.db_engine)
                await create_schema(app.state.db_engine)
            if startup:
                await startup(app)
        except Exception:
            await app.state.producer.stop()
            if getattr(app.state, "db_engine", None):
                await app.state.db_engine.dispose()
            raise
        try:
            yield
        finally:
            if shutdown:
                await shutdown(app)
            await app.state.producer.stop()
            if getattr(app.state, "db_engine", None):
                await app.state.db_engine.dispose()

    app = FastAPI(title=title, lifespan=lifespan)
    setup_tracing(app, settings)

    install_exception_handlers(app, logger)

    @app.middleware("http")
    async def log_http_io(request: Request, call_next):
        trace_id = request_trace_id(request)
        path = request.url.path
        if path in _SKIP_HTTP_LOG_PATHS:
            response = await call_next(request)
            response.headers.setdefault("x-trace-id", trace_id)
            return response

        started = perf_counter()
        if path in _OMIT_HTTP_REQUEST_BODY_PATHS:
            # Do not buffer high-volume alert payloads merely to omit them from
            # logs. Keeping the original receive stream also lowers peak memory
            # during alert bursts.
            request_body = None
            request_payload = "<omitted: high-volume ingestion payload>"
        else:
            request_body = await request.body()
            request_payload = _sanitize_http_payload(request_body, request.headers.get("content-type"))

        async def receive() -> dict[str, Any]:
            assert request_body is not None
            return {"type": "http.request", "body": request_body, "more_body": False}

        request_for_handler = request if request_body is None else Request(request.scope, receive)

        try:
            response = await call_next(request_for_handler)
        except Exception:
            logger.exception(
                "http_request_failed",
                extra={
                    "method": request.method,
                    "path": path,
                    "request": request_payload,
                    "latency_ms": int((perf_counter() - started) * 1000),
                },
            )
            raise

        response_payload = "<omitted: response body logging disabled>"

        logger.info(
            "http_io",
            extra={
                "method": request.method,
                "path": path,
                "status_code": response.status_code,
                "latency_ms": int((perf_counter() - started) * 1000),
                "request": request_payload,
                "response": response_payload,
            },
        )

        response.headers.setdefault("x-trace-id", trace_id)
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        if settings.database_enabled:
            engine = getattr(app.state, "db_engine", None)
            if engine is None:
                raise HTTPException(status_code=503, detail="database engine is not configured")
            try:
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
            except Exception as exc:
                raise HTTPException(status_code=503, detail="database is not ready") from exc
        return {"status": "ready", "service": settings.service_name}

    @app.get("/metrics")
    async def metrics():
        return metrics_response()

    return app
