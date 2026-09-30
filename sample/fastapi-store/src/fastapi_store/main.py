from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from presto_pay import AsyncPrestoPay

from fastapi_store.config import Settings, configure_logging, load_settings, log_startup
from fastapi_store.rendering import STATIC_DIR
from fastapi_store.routers import checkout, payments, webhooks
from fastapi_store.schemas import validation_failed
from fastapi_store.store import ActivityStore


def create_app(settings: Settings | None = None, presto: AsyncPrestoPay | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        resolved = settings or load_settings()
        client = presto or AsyncPrestoPay.from_env(resolved.presto_env)
        app.state.settings = resolved
        app.state.presto = client
        app.state.activity = ActivityStore()
        log_startup(resolved, "FastAPI")
        async with client:
            yield

    app = FastAPI(title="MyStore", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.add_exception_handler(RequestValidationError, validation_failed)
    app.include_router(checkout.router)
    app.include_router(payments.router)
    app.include_router(webhooks.router)
    return app


app = create_app()
