from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from mystore.config import Settings
from mystore.store import ActivityStore, CheckoutRecord, WebhookRecord
from presto_pay import (
    InitResult,
    PaymentMethod,
    PaymentStatus,
    PrestoPayApiError,
    PrestoPayError,
    PrestoPayResponseError,
    PrestoPaySignatureError,
    QueryResult,
    TxnType,
    WebhookEvent,
)

log = logging.getLogger("mystore")

MINIMUM_AMOUNT = Decimal("0.01")
MAXIMUM_MINOR_UNITS = 2**31 - 1
SUCCESS_STATUSES = {PaymentStatus.AUTHORISED, PaymentStatus.REFUNDED}
PENDING_STATUSES = {PaymentStatus.PENDING_AUTHORISE, PaymentStatus.PENDING_REVERSE, PaymentStatus.PENDING_REFUND}
FAILED_STATUSES = {PaymentStatus.FAILED, PaymentStatus.CANCELLED, PaymentStatus.EXPIRED}


@dataclass(frozen=True, slots=True)
class CheckoutForm:
    display_desc: str
    amount_in_ringgit: Decimal
    show_payment_methods: bool
    page_title: str | None
    selected_payment_method: str | None
    receipt_name: str | None
    receipt_email: str | None


def default_form() -> dict[str, Any]:
    return {
        "page_title": "MyStore",
        "display_desc": "Checkout demo",
        "amount_in_ringgit": "10.00",
        "show_payment_methods": False,
        "selected_payment_method": PaymentMethod.PM_PG_CARD.value,
        "receipt_name": "",
        "receipt_email": "",
    }


def parse_checkout(payload: object) -> tuple[CheckoutForm | None, dict[str, str]]:
    data: dict[str, Any] = payload if isinstance(payload, dict) else {}
    errors: dict[str, str] = {}

    display_desc = _text(data.get("displayDesc"))
    if not display_desc:
        errors["displayDesc"] = "Description is required"
    elif len(display_desc) > 200:
        errors["displayDesc"] = "Description must be at most 200 characters"

    amount = _decimal(data.get("amountInRinggit"))
    if amount is None:
        errors["amountInRinggit"] = "Amount is required"
    elif amount < MINIMUM_AMOUNT:
        errors["amountInRinggit"] = "Amount must be at least 0.01"
    elif to_minor_units(amount) > MAXIMUM_MINOR_UNITS:
        errors["amountInRinggit"] = "Amount is too large"

    show_payment_methods = data.get("showPaymentMethods") is True
    selected_payment_method = _text(data.get("selectedPaymentMethod"))
    if show_payment_methods and not selected_payment_method:
        errors["selectedPaymentMethod"] = "Select a payment method"

    page_title = _text(data.get("pageTitle"))
    receipt_name = _text(data.get("receiptName"))
    receipt_email = _text(data.get("receiptEmail"))
    for field, value, limit in (
        ("pageTitle", page_title, 80),
        ("receiptName", receipt_name, 200),
        ("receiptEmail", receipt_email, 320),
    ):
        if len(value) > limit:
            errors[field] = f"Must be at most {limit} characters"

    if errors or amount is None:
        return None, errors
    return (
        CheckoutForm(
            display_desc=display_desc,
            amount_in_ringgit=amount,
            show_payment_methods=show_payment_methods,
            page_title=page_title or None,
            selected_payment_method=selected_payment_method or None,
            receipt_name=receipt_name or None,
            receipt_email=receipt_email or None,
        ),
        {},
    )


def to_minor_units(amount_in_ringgit: Decimal) -> int:
    return int((amount_in_ringgit * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def next_txn_ref_num() -> str:
    return "demo-" + uuid.uuid4().hex[:16]


def init_arguments(form: CheckoutForm, settings: Settings, txn_ref_num: str) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "presto_mrn": settings.presto_mrn,
        "txn_type": TxnType.WEB_PAY,
        "txn_ref_num": txn_ref_num,
        "display_desc": form.display_desc,
        "amount": to_minor_units(form.amount_in_ringgit),
        "currency_code": settings.currency,
        "notify_url": settings.notify_url,
        "redirect_url": settings.return_url_for(txn_ref_num),
    }
    if form.show_payment_methods:
        arguments["allowed_payment_methods"] = [form.selected_payment_method]
        arguments["receipt_name"] = form.receipt_name
        arguments["receipt_email"] = form.receipt_email
        log.info(
            "Initiating self-hosted WebPay txnRefNum=%s amountMinorUnits=%s currency=%s allowedPaymentMethods=%s",
            txn_ref_num,
            arguments["amount"],
            settings.currency,
            form.selected_payment_method,
        )
    else:
        log.info(
            "Initiating hosted WebPay txnRefNum=%s amountMinorUnits=%s currency=%s",
            txn_ref_num,
            arguments["amount"],
            settings.currency,
        )
    return arguments


def record_checkout(store: ActivityStore, form: CheckoutForm, settings: Settings, result: InitResult) -> None:
    log.info(
        "WebPay init succeeded txnRefNum=%s paymentRefNum=%s paymentStatus=%s paymentUrlPresent=%s",
        result.txn_ref_num,
        result.payment_ref_num,
        result.payment_status,
        bool(result.payment_url),
    )
    store.save_checkout(
        CheckoutRecord(
            txn_ref_num=result.txn_ref_num or "",
            display_desc=form.display_desc,
            page_title=form.page_title if form.show_payment_methods else None,
            amount_minor_units=to_minor_units(form.amount_in_ringgit),
            currency_code=settings.currency,
            selected_payment_method=form.selected_payment_method if form.show_payment_methods else None,
            receipt_name=form.receipt_name if form.show_payment_methods else None,
            receipt_email=form.receipt_email if form.show_payment_methods else None,
            payment_ref_num=result.payment_ref_num,
            payment_status=result.payment_status,
            initiated_at=datetime.now().astimezone(),
        )
    )


def checkout_response(result: InitResult, txn_ref_num: str) -> dict[str, Any]:
    return {"paymentUrl": result.payment_url, "txnRefNum": result.txn_ref_num or txn_ref_num}


def gateway_failure(exc: PrestoPayError) -> dict[str, Any]:
    body: dict[str, Any] = {"message": str(exc)}
    if isinstance(exc, PrestoPayApiError):
        log.warning(
            "Checkout Presto API error kind=%s httpStatus=%s errorCode=%s message=%s",
            exc.kind,
            exc.http_status,
            exc.error_code,
            exc.error_message,
        )
        body["errorCode"] = exc.error_code
        body["errorMessage"] = exc.error_message
    elif isinstance(exc, PrestoPaySignatureError):
        log.warning("Checkout signature verification failed source=%s message=%s", exc.source, exc)
        body["signatureError"] = True
    elif isinstance(exc, PrestoPayResponseError):
        log.warning("Checkout received an unusable Presto response: %s; reconcile with query by txnRefNum", exc)
    else:
        log.warning("Checkout failed: %s", exc)
    body["mayHaveTakenEffect"] = exc.may_have_taken_effect
    return body


def return_page(
    txn_ref_num: str,
    store: ActivityStore,
    query: QueryResult | None,
    error: PrestoPayError | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "txn_ref_num": txn_ref_num,
        "checkout": store.find_checkout(txn_ref_num),
        "recent_webhooks": store.recent_webhooks(),
        "query": query,
        "query_error": str(error) if error is not None else None,
        "query_signature_error": isinstance(error, PrestoPaySignatureError),
        "signature_side": error.source.upper() if isinstance(error, PrestoPaySignatureError) else None,
    }
    if query is not None:
        status = query.payment_status or ""
        context["status"] = status
        context["status_kind"] = (
            "success"
            if status in SUCCESS_STATUSES
            else "pending"
            if status in PENDING_STATUSES
            else "failed"
            if status in FAILED_STATUSES
            else "other"
        )
        context["amount_text"] = format_ringgit(query.amount)
        detail = query.payment_details[0] if query.payment_details else None
        if detail is not None:
            context["payment_method_text"] = (
                f"{detail.method} • {detail.card_summary}" if detail.card_summary else detail.method
            )
    return context


def query_log(txn_ref_num: str, query: QueryResult) -> None:
    log.info(
        "Query completed txnRefNum=%s paymentRefNum=%s paymentStatus=%s amount=%s %s",
        txn_ref_num,
        query.payment_ref_num,
        query.payment_status,
        query.amount,
        query.currency_code,
    )


def format_ringgit(amount_minor_units: int | None) -> str:
    if amount_minor_units is None:
        return "-"
    return f"RM {Decimal(amount_minor_units) / 100:,.2f}"


def webhook_record(event: WebhookEvent) -> WebhookRecord:
    log.info(
        "Webhook verified eventCode=%s paymentStatus=%s txnRefNum=%s paymentRefNum=%s success=%s amount=%s %s "
        "eventRefNum=%s",
        event.event_code,
        event.payment_status,
        event.txn_ref_num,
        event.payment_ref_num,
        event.success,
        event.amount,
        event.currency_code,
        event.event_ref_num,
    )
    return WebhookRecord(
        event_ref_num=event.event_ref_num,
        txn_ref_num=event.txn_ref_num,
        event_code=event.event_code,
        payment_status=event.payment_status,
        success=event.success,
        amount_minor_units=event.amount,
        currency_code=event.currency_code,
        received_at=datetime.now().astimezone(),
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None
