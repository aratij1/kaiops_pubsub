from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.config import Settings
from common.database import create_engine, create_schema, create_session_factory
from common.kafka import KafkaProducer
from common.logging import configure_logging
from common.telemetry import metrics_response, setup_tracing


def create_app(
    *,
    title: str,
    settings: Settings,
    startup: Callable[[FastAPI], Awaitable[None]] | None = None,
    shutdown: Callable[[FastAPI], Awaitable[None]] | None = None,
) -> FastAPI:
    configure_logging(settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.producer = KafkaProducer(settings)
        await app.state.producer.start()
        if settings.database_enabled:
            app.state.db_engine = create_engine(settings)
            app.state.session_factory = create_session_factory(app.state.db_engine)
            await create_schema(app.state.db_engine)
        if startup:
            await startup(app)
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

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ready", "service": settings.service_name}

    @app.get("/metrics")
    async def metrics():
        return metrics_response()

    return app
