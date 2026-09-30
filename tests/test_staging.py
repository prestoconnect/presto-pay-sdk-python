from __future__ import annotations

import os
import time

import pytest

from presto_pay import ErrorCode, InitResult, PaymentStatus, PrestoPay, PrestoPayApiError, TxnType

pytestmark = [
    pytest.mark.staging,
    pytest.mark.skipif(
        os.environ.get("PRESTOPAY_STAGING_SMOKE") != "1",
        reason="set PRESTOPAY_STAGING_SMOKE=1 with staging credentials to call the real staging gateway",
    ),
]


@pytest.fixture
def presto() -> PrestoPay:
    return PrestoPay.from_env(os.environ, strict=True)


@pytest.fixture
def presto_mrn() -> str:
    mrn = os.environ.get("PRESTOPAY_MRN")
    if not mrn:
        pytest.fail("PRESTOPAY_MRN is required")
    return mrn


def _init(presto: PrestoPay, presto_mrn: str, txn_ref_num: str) -> InitResult:
    return presto.payments.init(
        presto_mrn=presto_mrn,
        txn_type=TxnType.WEB_PAY,
        txn_ref_num=txn_ref_num,
        display_desc="Python SDK staging smoke test",
        amount=100,
        currency_code="MYR",
        notify_url="https://example.invalid/presto/notify",
        redirect_url=f"https://example.invalid/presto/return/{txn_ref_num}",
    )


def test_payment_lifecycle(presto: PrestoPay, presto_mrn: str) -> None:
    txn_ref_num = f"py-smoke-{time.time_ns()}"
    with presto:
        created = _init(presto, presto_mrn, txn_ref_num)
        assert created.payment_url
        assert created.payment_status == PaymentStatus.PENDING_AUTHORISE

        queried = presto.payments.query(presto_mrn=presto_mrn, txn_ref_num=txn_ref_num)
        assert queried.payment_ref_num == created.payment_ref_num
        assert queried.payment_status == PaymentStatus.PENDING_AUTHORISE

        resent = _init(presto, presto_mrn, txn_ref_num)
        assert resent.payment_ref_num == created.payment_ref_num
        assert resent.payment_status == queried.payment_status

        reversed_payment = presto.payments.reverse(
            presto_mrn=presto_mrn,
            payment_ref_num=created.payment_ref_num,
            reversal_ref_num=f"py-smoke-rev-{time.time_ns()}",
            remark="staging smoke test",
        )
        assert reversed_payment.payment_status == PaymentStatus.CANCELLED

        second = _init(presto, presto_mrn, f"py-smoke-2-{time.time_ns()}")
        with pytest.raises(PrestoPayApiError) as caught:
            presto.payments.refund(
                presto_mrn=presto_mrn,
                payment_ref_num=second.payment_ref_num,
                refund_ref_num=f"py-smoke-rfnd-{time.time_ns()}",
                remark="staging smoke test",
            )
        assert caught.value.kind == "business"
        assert caught.value.error_code == ErrorCode.INVALID_STATUS_FOR_REFUND
        assert not caught.value.may_have_taken_effect
