from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from presto_pay import PaymentMethod, PrestoPayError

from fastapi_store import services
from fastapi_store.dependencies import ActivityDep, PrestoDep, SettingsDep
from fastapi_store.rendering import templates
from fastapi_store.schemas import CheckoutRequest

router = APIRouter()

DEFAULT_FORM: dict[str, Any] = {
    "page_title": "MyStore",
    "display_desc": "Checkout demo",
    "amount_in_ringgit": "10.00",
    "show_payment_methods": False,
    "selected_payment_method": PaymentMethod.PM_PG_CARD.value,
    "receipt_name": "",
    "receipt_email": "",
}


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, activity: ActivityDep) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"checkout": DEFAULT_FORM, "recent_webhooks": activity.recent_webhooks()},
    )


@router.post("/checkout")
async def submit(
    checkout: CheckoutRequest,
    presto: PrestoDep,
    settings: SettingsDep,
    activity: ActivityDep,
) -> JSONResponse:
    try:
        started = await services.start_checkout(presto, settings, activity, checkout)
    except PrestoPayError as exc:
        return JSONResponse(services.gateway_failure(exc), status_code=502)
    return JSONResponse({"paymentUrl": started.payment_url, "txnRefNum": started.txn_ref_num})
