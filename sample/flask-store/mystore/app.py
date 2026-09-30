from __future__ import annotations

import logging

from flask import Flask, Response, jsonify, request

from mystore import checkout
from mystore.config import Settings, configure_logging, load_settings, log_startup
from mystore.store import ActivityStore
from mystore.views import STATIC_JS_DIR, render_index, render_missing_return, render_return
from presto_pay import NotifyAck, PrestoPay, PrestoPayError

log = logging.getLogger("mystore")


def create_app(settings: Settings | None = None, presto: PrestoPay | None = None) -> Flask:
    configure_logging()
    settings = settings or load_settings()
    client = presto or PrestoPay.from_env(settings.presto_env)
    store = ActivityStore()
    app = Flask(__name__, static_folder=str(STATIC_JS_DIR), static_url_path="/js")

    @app.get("/")
    def home() -> str:
        return render_index(store)

    @app.post("/checkout")
    def submit_checkout() -> tuple[Response, int]:
        form, errors = checkout.parse_checkout(request.get_json(silent=True))
        if form is None:
            return jsonify(errors), 400
        txn_ref_num = checkout.next_txn_ref_num()
        try:
            result = client.payments.init(**checkout.init_arguments(form, settings, txn_ref_num))
        except PrestoPayError as exc:
            return jsonify(checkout.gateway_failure(exc)), 502
        checkout.record_checkout(store, form, settings, result)
        return jsonify(checkout.checkout_response(result, txn_ref_num)), 200

    @app.get("/return")
    def return_without_txn_ref() -> str:
        return render_missing_return(store)

    @app.get("/return/<txn_ref_num>")
    def return_page(txn_ref_num: str) -> str:
        txn_ref_num = txn_ref_num.strip()
        if not txn_ref_num:
            return render_missing_return(store)
        log.info("Querying payment txnRefNum=%s", txn_ref_num)
        try:
            query = client.payments.query(presto_mrn=settings.presto_mrn, txn_ref_num=txn_ref_num)
        except PrestoPayError as exc:
            log.warning("Query failed for txnRefNum=%s: %s", txn_ref_num, exc)
            return render_return(checkout.return_page(txn_ref_num, store, None, exc))
        checkout.query_log(txn_ref_num, query)
        return render_return(checkout.return_page(txn_ref_num, store, query, None))

    @app.post("/presto/notify")
    def presto_notify() -> Response:
        try:
            event = client.webhooks.verify(request.get_data())
            if not store.record_webhook(checkout.webhook_record(event)):
                log.info("Webhook eventRefNum=%s already processed; acknowledging again", event.event_ref_num)
            body = NotifyAck.OK
        except Exception as exc:
            log.warning("Webhook rejected: %s", exc)
            body = NotifyAck.for_error(exc)
        return Response(body, status=200, content_type=NotifyAck.CONTENT_TYPE)

    log_startup(settings, "Flask")
    return app
