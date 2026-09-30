from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from mystore import checkout
from mystore.config import Settings, configure_logging, load_settings, log_startup
from mystore.store import ActivityStore
from mystore.views import STATIC_JS_DIR, render_index, render_missing_return, render_return
from presto_pay import AsyncPrestoPay, NotifyAck, PrestoPayError

log = logging.getLogger("mystore")


def create_app(settings: Settings | None = None, presto: AsyncPrestoPay | None = None) -> FastAPI:
    configure_logging()
    resolved_settings = settings or load_settings()
    client = presto or AsyncPrestoPay.from_env(resolved_settings.presto_env)
    store = ActivityStore()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log_startup(resolved_settings, "FastAPI")
        async with client:
            yield

    app = FastAPI(title="MyStore", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/js", StaticFiles(directory=STATIC_JS_DIR), name="js")

    @app.get("/", response_class=HTMLResponse)
    async def home() -> str:
        return render_index(store)

    @app.post("/checkout")
    async def submit_checkout(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        form, errors = checkout.parse_checkout(payload)
        if form is None:
            return JSONResponse(errors, status_code=400)
        txn_ref_num = checkout.next_txn_ref_num()
        try:
            result = await client.payments.init(**checkout.init_arguments(form, resolved_settings, txn_ref_num))
        except PrestoPayError as exc:
            return JSONResponse(checkout.gateway_failure(exc), status_code=502)
        checkout.record_checkout(store, form, resolved_settings, result)
        return JSONResponse(checkout.checkout_response(result, txn_ref_num))

    @app.get("/return", response_class=HTMLResponse)
    async def return_without_txn_ref() -> str:
        return render_missing_return(store)

    @app.get("/return/{txn_ref_num}", response_class=HTMLResponse)
    async def return_page(txn_ref_num: str) -> str:
        txn_ref_num = txn_ref_num.strip()
        if not txn_ref_num:
            return render_missing_return(store)
        log.info("Querying payment txnRefNum=%s", txn_ref_num)
        try:
            query = await client.payments.query(presto_mrn=resolved_settings.presto_mrn, txn_ref_num=txn_ref_num)
        except PrestoPayError as exc:
            log.warning("Query failed for txnRefNum=%s: %s", txn_ref_num, exc)
            return render_return(checkout.return_page(txn_ref_num, store, None, exc))
        checkout.query_log(txn_ref_num, query)
        return render_return(checkout.return_page(txn_ref_num, store, query, None))

    @app.post("/presto/notify")
    async def presto_notify(request: Request) -> Response:
        try:
            event = client.webhooks.verify(await request.body())
            if not store.record_webhook(checkout.webhook_record(event)):
                log.info("Webhook eventRefNum=%s already processed; acknowledging again", event.event_ref_num)
            body = NotifyAck.OK
        except Exception as exc:
            log.warning("Webhook rejected: %s", exc)
            body = NotifyAck.for_error(exc)
        return Response(body, media_type=NotifyAck.CONTENT_TYPE)

    return app
