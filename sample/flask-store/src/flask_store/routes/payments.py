from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from flask import Blueprint, render_template
from presto_pay import PaymentStatus, PrestoPayError, PrestoPaySignatureError, QueryResult

from flask_store import extensions, services

bp = Blueprint("payments", __name__)
log = logging.getLogger(__name__)

STATUS_KINDS = {
    PaymentStatus.AUTHORISED: "success",
    PaymentStatus.REFUNDED: "success",
    PaymentStatus.PENDING_AUTHORISE: "pending",
    PaymentStatus.PENDING_REVERSE: "pending",
    PaymentStatus.PENDING_REFUND: "pending",
    PaymentStatus.FAILED: "failed",
    PaymentStatus.CANCELLED: "failed",
    PaymentStatus.EXPIRED: "failed",
}


@bp.get("/return")
def missing_reference() -> str:
    return render_template(
        "return.html",
        missing_txn_ref_num=True,
        recent_webhooks=extensions.activity().recent_webhooks(),
    )


@bp.get("/return/<txn_ref_num>")
def payment_result(txn_ref_num: str) -> str:
    txn_ref_num = txn_ref_num.strip()
    if not txn_ref_num:
        return missing_reference()
    store = extensions.activity()
    context: dict[str, Any] = {
        "txn_ref_num": txn_ref_num,
        "checkout": store.find_checkout(txn_ref_num),
        "recent_webhooks": store.recent_webhooks(),
    }
    try:
        query = services.find_payment(extensions.presto(), extensions.settings(), txn_ref_num)
    except PrestoPayError as exc:
        log.warning("Query failed for txnRefNum=%s: %s", txn_ref_num, exc)
        context |= _query_error(exc)
    else:
        context |= _payment_summary(query)
    return render_template("return.html", **context)


def _payment_summary(query: QueryResult) -> dict[str, Any]:
    status = query.payment_status or ""
    detail = query.payment_details[0] if query.payment_details else None
    method = None
    if detail is not None:
        method = f"{detail.method} • {detail.card_summary}" if detail.card_summary else detail.method
    return {
        "query": query,
        "status": status,
        "status_kind": STATUS_KINDS.get(status, "other"),
        "amount_text": _ringgit(query.amount),
        "payment_method_text": method,
    }


def _query_error(exc: PrestoPayError) -> dict[str, Any]:
    signature_error = isinstance(exc, PrestoPaySignatureError)
    return {
        "query_error": str(exc),
        "query_signature_error": signature_error,
        "signature_side": exc.source.upper() if isinstance(exc, PrestoPaySignatureError) else None,
    }


def _ringgit(amount_minor_units: int | None) -> str:
    if amount_minor_units is None:
        return "-"
    return f"RM {Decimal(amount_minor_units) / 100:,.2f}"
