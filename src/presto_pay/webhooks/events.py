from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from presto_pay._core.canonical import JsonScalar
from presto_pay._core.mapping import FieldReader
from presto_pay.constants import EventCode, PaymentStatus
from presto_pay.payments.results import PaymentDetail, read_payment_details


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    event_code: str
    mid: str
    presto_mrn: str
    payment_ref_num: str
    txn_ref_num: str
    event_ref_num: str
    event_ts: str
    amount: int
    currency_code: str
    ts: str
    success: bool
    user_ref_num: str | None
    additional_data: str | None
    payment_details: tuple[PaymentDetail, ...]
    payment_status: str
    raw: Mapping[str, JsonScalar] = field(repr=False, compare=False)


def derived_payment_status(event_code: str, success: bool) -> str:
    if event_code == EventCode.AUTHORISED:
        return PaymentStatus.AUTHORISED.value if success else PaymentStatus.FAILED.value
    return event_code


def map_event(reader: FieldReader) -> WebhookEvent:
    event_code = reader.required_str("eventCode")
    success = reader.required_bool("success")
    return WebhookEvent(
        event_code=event_code,
        mid=reader.required_str("mid"),
        presto_mrn=reader.required_str("prestoMrn"),
        payment_ref_num=reader.required_str("paymentRefNum"),
        txn_ref_num=reader.required_str("txnRefNum"),
        event_ref_num=reader.required_str("eventRefNum"),
        event_ts=reader.required_str("eventTs"),
        amount=reader.required_int("amount"),
        currency_code=reader.required_str("currencyCode"),
        ts=reader.required_str("ts"),
        success=success,
        user_ref_num=reader.optional_str("userRefNum"),
        additional_data=reader.optional_str("additionalData"),
        payment_details=read_payment_details(reader),
        payment_status=derived_payment_status(event_code, success),
        raw=dict(reader.body),
    )
