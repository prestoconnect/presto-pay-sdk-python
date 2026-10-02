from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from presto_pay import PaymentStatus, PrestoPayError, PrestoPaySignatureError, QueryResult

from fastapi_store import services
from fastapi_store.dependencies import ActivityDep, PrestoDep, SettingsDep
from fastapi_store.rendering import templates

router = APIRouter()
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


@router.get("/return", response_class=HTMLResponse)
async def missing_reference(request: Request, activity: ActivityDep) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "return.html",
        {"missing_txn_ref_num": True, "recent_webhooks": activity.recent_webhooks()},
    )


@router.get("/return/{txn_ref_num}", response_class=HTMLResponse)
async def payment_result(
    request: Request,
    txn_ref_num: str,
    presto: PrestoDep,
    settings: SettingsDep,
    activity: ActivityDep,
) -> HTMLResponse:
    txn_ref_num = txn_ref_num.strip()
    if not txn_ref_num:
        return await missing_reference(request, activity)
    context: dict[str, Any] = {
        "txn_ref_num": txn_ref_num,
        "checkout": activity.find_checkout(txn_ref_num),
        "recent_webhooks": activity.recent_webhooks(),
    }
    try:
        query = await services.find_payment(presto, settings, txn_ref_num)
    except PrestoPayError as exc:
        log.warning("Query failed for txnRefNum=%s: %s", txn_ref_num, exc)
        context |= _query_error(exc)
    else:
        services.apply_payment_status(activity, txn_ref_num, query.payment_status)
        context |= _payment_summary(query)
    return templates.TemplateResponse(request, "return.html", context)


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
    return {
        "query_error": str(exc),
        "query_signature_error": isinstance(exc, PrestoPaySignatureError),
        "signature_side": exc.source.upper() if isinstance(exc, PrestoPaySignatureError) else None,
    }


def _ringgit(amount_minor_units: int | None) -> str:
    if amount_minor_units is None:
        return "-"
    return f"RM {Decimal(amount_minor_units) / 100:,.2f}"
