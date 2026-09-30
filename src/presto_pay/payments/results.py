from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from presto_pay._core.canonical import JsonScalar
from presto_pay._core.mapping import FieldReader


@dataclass(frozen=True, slots=True)
class PaymentDetail:
    amount: int
    method: str | None
    card_bin: str | None = field(repr=False)
    card_summary: str | None = field(repr=False)
    card_type: str | None
    ref_num: str | None


@dataclass(frozen=True, slots=True)
class RefundDetail:
    refund_ref_num: str
    presto_refund_ref_num: str
    refund_status: str
    refund_request_date: str
    refund_finalised_date: str | None


@dataclass(frozen=True, slots=True)
class InitResult:
    presto_mrn: str
    payment_ref_num: str
    payment_status: str
    txn_ref_num: str | None
    payment_url: str | None
    user_ref_num: str | None
    amount: int | None
    currency_code: str | None
    payment_request_date: str | None
    payment_finalised_date: str | None
    additional_data: str | None
    ts: str
    raw: Mapping[str, JsonScalar] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class QueryResult:
    presto_mrn: str
    payment_ref_num: str
    txn_ref_num: str | None
    user_ref_num: str | None
    payment_status: str | None
    amount: int | None
    currency_code: str | None
    payment_request_date: str | None
    payment_finalised_date: str | None
    reversal_ref_num: str | None
    presto_reversal_ref_num: str | None
    reversal_status: str | None
    reversal_date: str | None
    refund_ref_num: str | None
    presto_refund_ref_num: str | None
    refund_status: str | None
    refund_request_date: str | None
    refund_finalised_date: str | None
    additional_data: str | None
    refund_details: tuple[RefundDetail, ...]
    payment_details: tuple[PaymentDetail, ...]
    ts: str
    raw: Mapping[str, JsonScalar] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ReverseResult:
    presto_mrn: str
    payment_ref_num: str
    presto_reversal_ref_num: str | None
    amount: int | None
    currency_code: str | None
    payment_status: str | None
    ts: str
    raw: Mapping[str, JsonScalar] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class RefundResult:
    presto_mrn: str
    payment_ref_num: str
    presto_refund_ref_num: str | None
    amount: int | None
    refund_amount: int | None
    currency_code: str | None
    payment_status: str | None
    refunded_date: str | None
    ts: str
    raw: Mapping[str, JsonScalar] = field(repr=False, compare=False)


def read_payment_details(reader: FieldReader) -> tuple[PaymentDetail, ...]:
    return tuple(
        PaymentDetail(
            amount=item.required_int("amount"),
            method=item.optional_str("method"),
            card_bin=item.optional_str("cardBin"),
            card_summary=item.optional_str("cardSummary"),
            card_type=item.optional_str("cardType"),
            ref_num=item.optional_str("refNum"),
        )
        for item in reader.nested("paymentDetails")
    )


def read_refund_details(reader: FieldReader) -> tuple[RefundDetail, ...]:
    return tuple(
        RefundDetail(
            refund_ref_num=item.required_str("refundRefNum"),
            presto_refund_ref_num=item.required_str("prestoRefundRefNum"),
            refund_status=item.required_str("refundStatus"),
            refund_request_date=item.required_str("refundRequestDate"),
            refund_finalised_date=item.optional_str("refundFinalisedDate"),
        )
        for item in reader.nested("refundDetails")
    )


def map_init(reader: FieldReader) -> InitResult:
    return InitResult(
        presto_mrn=reader.required_str("prestoMrn"),
        payment_ref_num=reader.required_str("paymentRefNum"),
        payment_status=reader.required_str("paymentStatus"),
        txn_ref_num=reader.optional_str("txnRefNum"),
        payment_url=reader.optional_str("paymentUrl"),
        user_ref_num=reader.optional_str("userRefNum"),
        amount=reader.optional_int("amount"),
        currency_code=reader.optional_str("currencyCode"),
        payment_request_date=reader.optional_str("paymentRequestDate"),
        payment_finalised_date=reader.optional_str("paymentFinalisedDate"),
        additional_data=reader.optional_str("additionalData"),
        ts=reader.required_str("ts"),
        raw=dict(reader.body),
    )


def map_query(reader: FieldReader) -> QueryResult:
    return QueryResult(
        presto_mrn=reader.required_str("prestoMrn"),
        payment_ref_num=reader.required_str("paymentRefNum"),
        txn_ref_num=reader.optional_str("txnRefNum"),
        user_ref_num=reader.optional_str("userRefNum"),
        payment_status=reader.optional_str("paymentStatus"),
        amount=reader.optional_int("amount"),
        currency_code=reader.optional_str("currencyCode"),
        payment_request_date=reader.optional_str("paymentRequestDate"),
        payment_finalised_date=reader.optional_str("paymentFinalisedDate"),
        reversal_ref_num=reader.optional_str("reversalRefNum"),
        presto_reversal_ref_num=reader.optional_str("prestoReversalRefNum"),
        reversal_status=reader.optional_str("reversalStatus"),
        reversal_date=reader.optional_str("reversalDate"),
        refund_ref_num=reader.optional_str("refundRefNum"),
        presto_refund_ref_num=reader.optional_str("prestoRefundRefNum"),
        refund_status=reader.optional_str("refundStatus"),
        refund_request_date=reader.optional_str("refundRequestDate"),
        refund_finalised_date=reader.optional_str("refundFinalisedDate"),
        additional_data=reader.optional_str("additionalData"),
        refund_details=read_refund_details(reader),
        payment_details=read_payment_details(reader),
        ts=reader.required_str("ts"),
        raw=dict(reader.body),
    )


def map_reverse(reader: FieldReader) -> ReverseResult:
    return ReverseResult(
        presto_mrn=reader.required_str("prestoMrn"),
        payment_ref_num=reader.required_str("paymentRefNum"),
        presto_reversal_ref_num=reader.optional_str("prestoReversalRefNum"),
        amount=reader.optional_int("amount"),
        currency_code=reader.optional_str("currencyCode"),
        payment_status=reader.optional_str("paymentStatus"),
        ts=reader.required_str("ts"),
        raw=dict(reader.body),
    )


def map_refund(reader: FieldReader) -> RefundResult:
    return RefundResult(
        presto_mrn=reader.required_str("prestoMrn"),
        payment_ref_num=reader.required_str("paymentRefNum"),
        presto_refund_ref_num=reader.optional_str("prestoRefundRefNum"),
        amount=reader.optional_int("amount"),
        refund_amount=reader.optional_int("refundAmount"),
        currency_code=reader.optional_str("currencyCode"),
        payment_status=reader.optional_str("paymentStatus"),
        refunded_date=reader.optional_str("refundedDate"),
        ts=reader.required_str("ts"),
        raw=dict(reader.body),
    )
