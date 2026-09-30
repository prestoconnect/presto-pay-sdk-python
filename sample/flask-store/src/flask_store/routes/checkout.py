from __future__ import annotations

from flask import Blueprint, Response, jsonify, render_template, request
from presto_pay import PrestoPayError

from flask_store import extensions, services
from flask_store.forms import CheckoutForm, default_form

bp = Blueprint("checkout", __name__)


@bp.get("/")
def home() -> str:
    return render_template(
        "index.html",
        checkout=default_form(),
        recent_webhooks=extensions.activity().recent_webhooks(),
    )


@bp.post("/checkout")
def submit() -> tuple[Response, int]:
    form, errors = CheckoutForm.from_json(request.get_json(silent=True))
    if form is None:
        return jsonify(errors), 400
    try:
        started = services.start_checkout(extensions.presto(), extensions.settings(), extensions.activity(), form)
    except PrestoPayError as exc:
        return jsonify(services.gateway_failure(exc)), 502
    return jsonify({"paymentUrl": started.payment_url, "txnRefNum": started.txn_ref_num}), 200
