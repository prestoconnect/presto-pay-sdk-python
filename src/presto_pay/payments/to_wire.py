from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Generic, TypeVar

from presto_pay._core.canonical import WireBody
from presto_pay._core.mapping import FieldReader
from presto_pay._core.protocol import INIT, QUERY, REFUND, REVERSE, OperationSpec
from presto_pay.constants import TxnType
from presto_pay.errors import ReconcileKey
from presto_pay.payments.inputs import LineItem, WireFields
from presto_pay.payments.results import (
    InitResult,
    QueryResult,
    RefundResult,
    ReverseResult,
    map_init,
    map_query,
    map_refund,
    map_reverse,
)

T = TypeVar("T")

INIT_LENGTHS = {
    "txnRefNum": 50,
    "displayDesc": 255,
    "deviceRefNum": 50,
    "deviceIp": 50,
    "notifyUrl": 255,
    "redirectUrl": 255,
    "additionalData": 255,
    "mode": 50,
    "modeData": 1000,
    "receiptEmail": 320,
    "receiptName": 200,
}
REVERSE_LENGTHS = {"reversalRefNum": 50, "remark": 200, "notifyUrl": 255}
REFUND_LENGTHS = {"refundRefNum": 50, "remark": 200, "notifyUrl": 255}


@dataclass(frozen=True, slots=True)
class Call(Generic[T]):
    operation: OperationSpec
    fields: WireBody
    reconcile_by: ReconcileKey | None
    mapper: Callable[[FieldReader], T] = field(repr=False)
    documented_lengths: Mapping[str, int] = field(default_factory=dict, repr=False)


def init(
    *,
    presto_mrn: str,
    txn_type: TxnType | str,
    txn_ref_num: str,
    display_desc: str,
    qr_value: str | None = None,
    payer_ref_num: str | None = None,
    device_ref_num: str | None = None,
    device_ip: str | None = None,
    item_list: Sequence[LineItem] | None = None,
    transactional_data: str | None = None,
    amount: int | None = None,
    currency_code: str | None = None,
    notify_url: str | None = None,
    redirect_url: str | None = None,
    session_validity: datetime | str | None = None,
    additional_data: str | None = None,
    mode: str | None = None,
    mode_data: str | None = None,
    allowed_payment_methods: Sequence[str] | None = None,
    bind_data: str | None = None,
    theme_ref_num: str | None = None,
    receipt_email: str | None = None,
    receipt_name: str | None = None,
) -> Call[InitResult]:
    fields = WireFields("init")
    fields.text("presto_mrn", presto_mrn, required=True)
    fields.text("txn_type", txn_type, required=True)
    fields.text("txn_ref_num", txn_ref_num, required=True)
    fields.text("display_desc", display_desc, required=True)
    fields.text("qr_value", qr_value)
    fields.text("payer_ref_num", payer_ref_num)
    fields.text("device_ref_num", device_ref_num)
    fields.text("device_ip", device_ip)
    fields.line_items("item_list", item_list)
    fields.text("transactional_data", transactional_data)
    fields.amount("amount", amount)
    fields.text("currency_code", currency_code)
    fields.text("notify_url", notify_url)
    fields.text("redirect_url", redirect_url)
    fields.timestamp("session_validity", session_validity)
    fields.text("additional_data", additional_data)
    fields.text("mode", mode)
    fields.text("mode_data", mode_data)
    fields.codes("allowed_payment_methods", allowed_payment_methods)
    fields.text("bind_data", bind_data)
    fields.text("theme_ref_num", theme_ref_num)
    fields.text("receipt_email", receipt_email)
    fields.text("receipt_name", receipt_name)

    if fields.is_set("qr_value") and fields.is_set("payer_ref_num"):
        raise fields.error("payer_ref_num", "qr_value and payer_ref_num are mutually exclusive; pass only one")
    if fields.is_set("amount") and not fields.is_set("currency_code"):
        raise fields.error("currency_code", "currency_code is required when amount is set")
    if txn_type == TxnType.WEB_PAY and not fields.is_set("redirect_url"):
        raise fields.error("redirect_url", "redirect_url is required when txn_type is WebPay")

    return Call(
        INIT,
        fields.values,
        {"presto_mrn": presto_mrn, "txn_ref_num": txn_ref_num},
        map_init,
        INIT_LENGTHS,
    )


def query(
    *,
    presto_mrn: str,
    payment_ref_num: str | None = None,
    txn_ref_num: str | None = None,
) -> Call[QueryResult]:
    fields = WireFields("query")
    fields.text("presto_mrn", presto_mrn, required=True)
    fields.text("payment_ref_num", payment_ref_num)
    fields.text("txn_ref_num", txn_ref_num)
    if not fields.is_set("payment_ref_num") and not fields.is_set("txn_ref_num"):
        raise fields.error("payment_ref_num", "query needs payment_ref_num or txn_ref_num")
    return Call(QUERY, fields.values, None, map_query)


def reverse(
    *,
    presto_mrn: str,
    reversal_ref_num: str,
    payment_ref_num: str | None = None,
    txn_ref_num: str | None = None,
    remark: str | None = None,
    notify_url: str | None = None,
) -> Call[ReverseResult]:
    fields = WireFields("reverse")
    fields.text("presto_mrn", presto_mrn, required=True)
    fields.text("reversal_ref_num", reversal_ref_num, required=True)
    fields.text("payment_ref_num", payment_ref_num)
    fields.text("txn_ref_num", txn_ref_num)
    fields.text("remark", remark)
    fields.text("notify_url", notify_url)
    reconcile_by: ReconcileKey
    if payment_ref_num:
        reconcile_by = {"presto_mrn": presto_mrn, "payment_ref_num": payment_ref_num}
    elif txn_ref_num:
        reconcile_by = {"presto_mrn": presto_mrn, "txn_ref_num": txn_ref_num}
    else:
        raise fields.error("payment_ref_num", "reverse needs payment_ref_num or txn_ref_num")
    return Call(REVERSE, fields.values, reconcile_by, map_reverse, REVERSE_LENGTHS)


def refund(
    *,
    presto_mrn: str,
    payment_ref_num: str,
    refund_ref_num: str,
    remark: str,
    notify_url: str | None = None,
    amount: int | None = None,
) -> Call[RefundResult]:
    fields = WireFields("refund")
    fields.text("presto_mrn", presto_mrn, required=True)
    fields.text("payment_ref_num", payment_ref_num, required=True)
    fields.text("refund_ref_num", refund_ref_num, required=True)
    fields.text("remark", remark, required=True)
    fields.text("notify_url", notify_url)
    fields.amount("amount", amount)
    return Call(
        REFUND,
        fields.values,
        {"presto_mrn": presto_mrn, "payment_ref_num": payment_ref_num},
        map_refund,
        REFUND_LENGTHS,
    )
