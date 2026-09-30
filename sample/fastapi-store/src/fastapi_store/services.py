from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from presto_pay import (
    AsyncPrestoPay,
    InitResult,
    NotifyAck,
    PrestoPayApiError,
    PrestoPayError,
    PrestoPayResponseError,
    PrestoPaySignatureError,
    QueryResult,
    TxnType,
)

from fastapi_store.config import Settings
from fastapi_store.schemas import CheckoutRequest
from fastapi_store.store import ActivityStore, CheckoutRecord, WebhookRecord

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CheckoutStarted:
    payment_url: str | None
    txn_ref_num: str


async def start_checkout(
    presto: AsyncPrestoPay, settings: Settings, store: ActivityStore, form: CheckoutRequest
) -> CheckoutStarted:
    txn_ref_num = "demo-" + uuid.uuid4().hex[:16]
    result = await presto.payments.init(**_init_arguments(form, settings, txn_ref_num))
    log.info(
        "WebPay init succeeded txnRefNum=%s paymentRefNum=%s paymentStatus=%s paymentUrlPresent=%s",
        result.txn_ref_num,
        result.payment_ref_num,
        result.payment_status,
        bool(result.payment_url),
    )
    store.save_checkout(_checkout_record(form, settings, result, txn_ref_num))
    return CheckoutStarted(payment_url=result.payment_url, txn_ref_num=result.txn_ref_num or txn_ref_num)


async def find_payment(presto: AsyncPrestoPay, settings: Settings, txn_ref_num: str) -> QueryResult:
    log.info("Querying payment txnRefNum=%s", txn_ref_num)
    query = await presto.payments.query(presto_mrn=settings.presto_mrn, txn_ref_num=txn_ref_num)
    log.info(
        "Query completed txnRefNum=%s paymentRefNum=%s paymentStatus=%s amount=%s %s",
        txn_ref_num,
        query.payment_ref_num,
        query.payment_status,
        query.amount,
        query.currency_code,
    )
    return query


def accept_webhook(presto: AsyncPrestoPay, store: ActivityStore, body: bytes) -> bytes:
    try:
        event = presto.webhooks.verify(body)
    except Exception as exc:
        log.warning("Webhook rejected: %s", exc)
        return NotifyAck.for_error(exc)
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
    recorded = store.record_webhook(
        WebhookRecord(
            event_ref_num=event.event_ref_num,
            txn_ref_num=event.txn_ref_num,
            event_code=event.event_code,
            payment_status=event.payment_status,
            success=event.success,
            amount_minor_units=event.amount,
            currency_code=event.currency_code,
            received_at=datetime.now().astimezone(),
        )
    )
    if not recorded:
        log.info("Webhook eventRefNum=%s already processed; acknowledging again", event.event_ref_num)
    return NotifyAck.OK


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


def _init_arguments(form: CheckoutRequest, settings: Settings, txn_ref_num: str) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "presto_mrn": settings.presto_mrn,
        "txn_type": TxnType.WEB_PAY,
        "txn_ref_num": txn_ref_num,
        "display_desc": form.display_desc,
        "amount": form.amount_minor_units,
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
            form.amount_minor_units,
            settings.currency,
            form.selected_payment_method,
        )
    else:
        log.info(
            "Initiating hosted WebPay txnRefNum=%s amountMinorUnits=%s currency=%s",
            txn_ref_num,
            form.amount_minor_units,
            settings.currency,
        )
    return arguments


def _checkout_record(form: CheckoutRequest, settings: Settings, result: InitResult, txn_ref_num: str) -> CheckoutRecord:
    self_hosted = form.show_payment_methods
    return CheckoutRecord(
        txn_ref_num=result.txn_ref_num or txn_ref_num,
        display_desc=form.display_desc,
        page_title=form.page_title if self_hosted else None,
        amount_minor_units=form.amount_minor_units,
        currency_code=settings.currency,
        selected_payment_method=form.selected_payment_method if self_hosted else None,
        receipt_name=form.receipt_name if self_hosted else None,
        receipt_email=form.receipt_email if self_hosted else None,
        payment_ref_num=result.payment_ref_num,
        payment_status=result.payment_status,
        initiated_at=datetime.now().astimezone(),
    )
