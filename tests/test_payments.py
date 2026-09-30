from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from conftest import (
    MID,
    MRN,
    NOW_TS,
    Gateway,
    async_client,
    business_error,
    init_success,
    load_vectors,
    ok,
    raw_success,
    sync_client,
    verifies_as_merchant,
)
from presto_pay import (
    InitResult,
    LineItem,
    PaymentMethod,
    PaymentStatus,
    PrestoPayApiError,
    PrestoPayConfigError,
    PrestoPayError,
    PrestoPayResponseError,
    PrestoPaySignatureError,
    PrestoPayTransportError,
    QueryResult,
    TxnType,
)

WEB_PAY: dict[str, Any] = {
    "presto_mrn": MRN,
    "txn_type": TxnType.WEB_PAY,
    "txn_ref_num": "order-123",
    "display_desc": "Order 123",
    "amount": 10_000,
    "currency_code": "MYR",
    "notify_url": "https://shop.example/presto/notify",
    "redirect_url": "https://shop.example/presto/return",
}

QUERY_CAPTURE = next(c for c in load_vectors("canonical.json")["cases"] if c["name"].startswith("staging-query"))[
    "body"
]


def query_success(**overrides: Any) -> dict[str, Any]:
    body = {key: value for key, value in QUERY_CAPTURE.items() if key != "signature"}
    body.update({"prestoMrn": MRN, "txnRefNum": "order-123"}, **overrides)
    return body


def reverse_success(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "prestoMrn": MRN,
        "paymentRefNum": "PP1",
        "prestoReversalRefNum": "PR1",
        "amount": 10000,
        "currencyCode": "MYR",
        "paymentStatus": "Cancelled",
        "success": True,
        "ts": NOW_TS,
        "errorCode": "",
        "errorMessage": "",
    }
    return body | overrides


def refund_success(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "prestoMrn": MRN,
        "paymentRefNum": "PP1",
        "prestoRefundRefNum": "PF1",
        "amount": 10000,
        "refundAmount": 2500,
        "currencyCode": "MYR",
        "paymentStatus": "PartialRefunded",
        "refundedDate": NOW_TS,
        "success": True,
        "ts": NOW_TS,
        "errorCode": "",
        "errorMessage": "",
    }
    return body | overrides


class TestInit:
    def test_wire_body(self) -> None:
        gateway = Gateway(ok(init_success()))
        with sync_client(gateway) as presto:
            presto.payments.init(
                **WEB_PAY,
                allowed_payment_methods=[PaymentMethod.WALLET, "Card"],
                item_list=[LineItem(item_desc="Tea", quantity=2, unit_amount=500, total_amount=1000)],
                session_validity=datetime(2026, 9, 24, 6, 0, tzinfo=UTC),
            )
        (body,) = gateway.bodies()
        assert verifies_as_merchant(body)
        assert {key: value for key, value in body.items() if key not in ("ts", "signature")} == {
            "prestoMrn": MRN,
            "txnType": "WebPay",
            "txnRefNum": "order-123",
            "displayDesc": "Order 123",
            "amount": 10000,
            "currencyCode": "MYR",
            "notifyUrl": "https://shop.example/presto/notify",
            "redirectUrl": "https://shop.example/presto/return",
            "allowedPaymentMethods": '["Wallet","Card"]',
            "itemList": '[{"itemDesc":"Tea","quantity":2,"unitAmount":500,"totalAmount":1000}]',
            "sessionValidity": "20260924140000.000",
            "mid": MID,
        }

    def test_unset_optionals_are_omitted_never_null(self) -> None:
        gateway = Gateway(ok(init_success()))
        with sync_client(gateway) as presto:
            presto.payments.init(presto_mrn=MRN, txn_type=TxnType.QR_PAY, txn_ref_num="order-123", display_desc="x")
        assert set(gateway.bodies()[0]) == {
            "prestoMrn",
            "txnType",
            "txnRefNum",
            "displayDesc",
            "mid",
            "ts",
            "signature",
        }

    def test_result(self) -> None:
        with sync_client(Gateway(ok(init_success()))) as presto:
            result = presto.payments.init(**WEB_PAY)
        assert isinstance(result, InitResult)
        assert result.payment_ref_num == "PP260924K4H3DSF"
        assert result.payment_status == PaymentStatus.PENDING_AUTHORISE
        assert result.user_ref_num is None
        assert result.payment_finalised_date is None
        assert result.additional_data is None
        assert result.amount == 10000
        assert result.raw["userRefNum"] == ""
        assert dataclasses.asdict(result)["payment_url"] == result.payment_url

    def test_results_are_frozen(self) -> None:
        with sync_client(Gateway(ok(init_success()))) as presto:
            result = presto.payments.init(**WEB_PAY)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.payment_status = "Authorised"  # type: ignore[misc]

    def test_unknown_status_passes_through(self) -> None:
        with sync_client(Gateway(ok(init_success(paymentStatus="SomethingNew")))) as presto:
            result = presto.payments.init(**WEB_PAY)
        assert result.payment_status == "SomethingNew"
        assert PaymentStatus.try_parse(result.payment_status) is None

    def test_empty_required_field_is_malformed_and_ambiguous(self) -> None:
        with (
            sync_client(Gateway(ok(init_success(paymentStatus="")))) as presto,
            pytest.raises(PrestoPayResponseError, match="paymentStatus") as caught,
        ):
            presto.payments.init(**WEB_PAY)
        assert caught.value.may_have_taken_effect
        assert caught.value.reconcile_by == {"presto_mrn": MRN, "txn_ref_num": "order-123"}

    def test_reconcile_by_feeds_query_directly(self) -> None:
        gateway = Gateway(
            httpx.ReadTimeout("slow"),
            ok(query_success(paymentStatus="PendingAuthorise")),
        )
        with sync_client(gateway) as presto:
            with pytest.raises(PrestoPayError) as caught:
                presto.payments.init(**WEB_PAY)
            assert caught.value.may_have_taken_effect
            assert caught.value.reconcile_by is not None
            recovered = presto.payments.query(**caught.value.reconcile_by)
        assert isinstance(recovered, QueryResult)
        assert gateway.bodies()[1]["txnRefNum"] == "order-123"

    def test_business_error_did_not_take_effect(self) -> None:
        with (
            sync_client(Gateway(ok(business_error("1201", "Invalid input.")))) as presto,
            pytest.raises(PrestoPayApiError) as caught,
        ):
            presto.payments.init(**WEB_PAY)
        assert caught.value.error_code == "1201"
        assert caught.value.operation == "init"
        assert not caught.value.may_have_taken_effect


class TestInitValidation:
    @pytest.mark.parametrize(
        ("overrides", "field", "message"),
        [
            ({"txn_ref_num": ""}, "txn_ref_num", "required"),
            ({"display_desc": None}, "display_desc", "required"),
            ({"amount": 12.0}, "amount", "must be an int in minor currency units"),
            ({"amount": True}, "amount", "must be an int"),
            ({"amount": 0}, "amount", "greater than 0"),
            ({"amount": -5}, "amount", "greater than 0"),
            ({"currency_code": None}, "currency_code", "required when amount is set"),
            ({"redirect_url": None}, "redirect_url", "required when txn_type is WebPay"),
            ({"qr_value": "QR", "payer_ref_num": "P1"}, "payer_ref_num", "mutually exclusive"),
            ({"display_desc": "bad \udcff"}, "display_desc", "unpaired surrogate"),
            ({"notify_url": 42}, "notify_url", "must be a str"),
            ({"allowed_payment_methods": "Wallet"}, "allowed_payment_methods", "must be a list"),
            ({"allowed_payment_methods": []}, "allowed_payment_methods", "must not be empty"),
            ({"allowed_payment_methods": ["Wallet", 3]}, "allowed_payment_methods[1]", "must be a str"),
            ({"session_validity": "tomorrow"}, "session_validity", "yyyyMMddHHmmss.SSS"),
            ({"session_validity": datetime(2026, 1, 1)}, "session_validity", "aware"),
            (
                {"item_list": [LineItem(item_desc="Tea", quantity=0, unit_amount=1, total_amount=1)]},
                "item_list[0].quantity",
                "greater than 0",
            ),
            (
                {"item_list": [LineItem(item_desc="", quantity=1, unit_amount=1, total_amount=1)]},
                "item_list[0].item_desc",
                "required",
            ),
            ({"item_list": [{"itemDesc": "Tea"}]}, "item_list[0]", "must be a LineItem"),
        ],
    )
    def test_rejected_before_anything_is_sent(self, overrides: dict[str, Any], field: str, message: str) -> None:
        gateway = Gateway()
        with sync_client(gateway) as presto, pytest.raises(PrestoPayConfigError, match=message) as caught:
            presto.payments.init(**(WEB_PAY | overrides))
        assert caught.value.field == field
        assert caught.value.operation == "init"
        assert gateway.requests == []

    def test_documented_lengths_are_not_enforced_by_default(self) -> None:
        gateway = Gateway(ok(init_success()))
        with sync_client(gateway) as presto:
            presto.payments.init(**(WEB_PAY | {"display_desc": "x" * 300}))
        assert len(gateway.requests) == 1

    def test_strict_mode_enforces_documented_lengths(self) -> None:
        with (
            sync_client(Gateway(), strict=True) as presto,
            pytest.raises(PrestoPayConfigError, match="documented maximum is 255") as caught,
        ):
            presto.payments.init(**(WEB_PAY | {"display_desc": "x" * 256}))
        assert caught.value.field == "display_desc"


class TestQuery:
    def test_needs_a_reference(self) -> None:
        with sync_client(Gateway()) as presto, pytest.raises(PrestoPayConfigError, match="payment_ref_num or txn"):
            presto.payments.query(presto_mrn=MRN)

    def test_captured_query_response_maps(self) -> None:
        with sync_client(Gateway(ok(query_success()))) as presto:
            result = presto.payments.query(presto_mrn=MRN, txn_ref_num="order-123")
        assert result.payment_status == "Expired"
        assert result.refund_details == ()
        assert result.payment_details == ()
        assert result.user_ref_num is None
        assert result.reversal_status is None
        assert result.reversal_date is None

    def test_stringified_lists_become_real_lists(self) -> None:
        details = json.dumps(
            [
                {
                    "amount": 10000,
                    "method": "Card",
                    "cardBin": "411111",
                    "cardSummary": "4111****1111",
                    "cardType": "Visa",
                }
            ]
        )
        refunds = json.dumps(
            [
                {
                    "refundRefNum": "R1",
                    "prestoRefundRefNum": "PR1",
                    "refundStatus": "Success",
                    "refundRequestDate": NOW_TS,
                    "refundFinalisedDate": "",
                }
            ]
        )
        with sync_client(Gateway(ok(query_success(paymentDetails=details, refundDetails=refunds)))) as presto:
            result = presto.payments.query(presto_mrn=MRN, payment_ref_num="PP260924K4H3DSF")
        (payment,) = result.payment_details
        assert (payment.amount, payment.method, payment.card_bin) == (10000, "Card", "411111")
        assert "411111" not in repr(payment)
        (refund,) = result.refund_details
        assert refund.refund_status == "Success"
        assert refund.refund_finalised_date is None

    def test_missing_list_fields_read_as_empty(self) -> None:
        body = query_success()
        del body["paymentDetails"], body["refundDetails"]
        with sync_client(Gateway(ok(body))) as presto:
            result = presto.payments.query(presto_mrn=MRN, txn_ref_num="order-123")
        assert result.payment_details == ()

    def test_malformed_list_on_query_did_not_take_effect(self) -> None:
        with (
            sync_client(Gateway(ok(query_success(paymentDetails="[1,2]")))) as presto,
            pytest.raises(PrestoPayResponseError) as caught,
        ):
            presto.payments.query(presto_mrn=MRN, txn_ref_num="order-123")
        assert not caught.value.may_have_taken_effect

    def test_strict_mode_rejects_coercible_drift(self) -> None:
        body = query_success(userRefNum=12345)
        with sync_client(Gateway(ok(body))) as presto:
            assert presto.payments.query(presto_mrn=MRN, txn_ref_num="order-123").user_ref_num == "12345"
        with sync_client(Gateway(ok(body)), strict=True) as presto, pytest.raises(PrestoPayResponseError):
            presto.payments.query(presto_mrn=MRN, txn_ref_num="order-123")


class TestReverse:
    def test_wire_body_and_result(self) -> None:
        gateway = Gateway(ok(reverse_success()))
        with sync_client(gateway) as presto:
            result = presto.payments.reverse(
                presto_mrn=MRN, payment_ref_num="PP1", reversal_ref_num="rev-1", remark="customer cancelled"
            )
        assert result.payment_status == PaymentStatus.CANCELLED
        assert result.presto_reversal_ref_num == "PR1"
        body = gateway.bodies()[0]
        assert (body["paymentRefNum"], body["reversalRefNum"], body["remark"]) == ("PP1", "rev-1", "customer cancelled")

    def test_needs_a_reference(self) -> None:
        with sync_client(Gateway()) as presto, pytest.raises(PrestoPayConfigError, match="payment_ref_num or txn"):
            presto.payments.reverse(presto_mrn=MRN, reversal_ref_num="rev-1")

    @pytest.mark.parametrize(
        ("reference", "expected"),
        [
            ({"payment_ref_num": "PP1"}, {"presto_mrn": MRN, "payment_ref_num": "PP1"}),
            ({"txn_ref_num": "order-123"}, {"presto_mrn": MRN, "txn_ref_num": "order-123"}),
        ],
    )
    def test_ambiguous_failure_reconciles_by_the_reference_given(
        self, reference: dict[str, str], expected: dict[str, str]
    ) -> None:
        with sync_client(Gateway(httpx.Response(502))) as presto, pytest.raises(PrestoPayApiError) as caught:
            presto.payments.reverse(presto_mrn=MRN, reversal_ref_num="rev-1", **reference)
        assert caught.value.may_have_taken_effect
        assert caught.value.reconcile_by == expected


class TestRefund:
    def test_wire_body_and_result(self) -> None:
        gateway = Gateway(ok(refund_success()))
        with sync_client(gateway) as presto:
            result = presto.payments.refund(
                presto_mrn=MRN, payment_ref_num="PP1", refund_ref_num="rf-1", remark="damaged", amount=2500
            )
        assert (result.amount, result.refund_amount, result.refunded_date) == (10000, 2500, NOW_TS)
        assert gateway.bodies()[0]["amount"] == 2500

    def test_full_refund_omits_amount(self) -> None:
        gateway = Gateway(ok(refund_success()))
        with sync_client(gateway) as presto:
            presto.payments.refund(presto_mrn=MRN, payment_ref_num="PP1", refund_ref_num="rf-1", remark="damaged")
        assert "amount" not in gateway.bodies()[0]

    def test_remark_is_required(self) -> None:
        with sync_client(Gateway()) as presto, pytest.raises(PrestoPayConfigError, match="remark is required"):
            presto.payments.refund(presto_mrn=MRN, payment_ref_num="PP1", refund_ref_num="rf-1", remark="")

    def test_pending_payment_refund_is_a_business_error(self) -> None:
        with (
            sync_client(Gateway(ok(business_error("1227", "Invalid payment status")))) as presto,
            pytest.raises(PrestoPayApiError) as caught,
        ):
            presto.payments.refund(presto_mrn=MRN, payment_ref_num="PP1", refund_ref_num="rf-1", remark="x")
        assert caught.value.error_code == "1227"
        assert not caught.value.may_have_taken_effect

    def test_connect_failure_is_retried_because_nothing_was_sent(self) -> None:
        gateway = Gateway(httpx.ConnectError("refused"), ok(refund_success()))
        with sync_client(gateway) as presto:
            presto.payments.refund(presto_mrn=MRN, payment_ref_num="PP1", refund_ref_num="rf-1", remark="x")
        assert len(gateway.requests) == 2

    def test_read_failure_is_not_retried(self) -> None:
        gateway = Gateway(httpx.ReadError("reset"))
        with sync_client(gateway) as presto, pytest.raises(PrestoPayTransportError) as caught:
            presto.payments.refund(presto_mrn=MRN, payment_ref_num="PP1", refund_ref_num="rf-1", remark="x")
        assert caught.value.reconcile_by == {"presto_mrn": MRN, "payment_ref_num": "PP1"}


@pytest.mark.parametrize("case", load_vectors("refund-policy.json")["cases"], ids=lambda case: case["paymentMethod"])
def test_refund_is_never_rejected_for_its_payment_method(case: dict[str, Any]) -> None:
    assert case["requestable"]
    payment = query_success(paymentDetails=json.dumps([{"amount": 10000, "method": case["paymentMethod"]}]))
    gateway = Gateway(ok(payment), ok(refund_success()))
    with sync_client(gateway) as presto:
        method = presto.payments.query(presto_mrn=MRN, txn_ref_num="order-123").payment_details[0].method
        assert method == case["paymentMethod"]
        presto.payments.refund(presto_mrn=MRN, payment_ref_num="PP1", refund_ref_num="rf-1", remark="x")
    assert len(gateway.requests) == 2


class TestAsyncPayments:
    @pytest.mark.anyio
    async def test_every_operation(self) -> None:
        gateway = Gateway(ok(init_success()), ok(query_success()), ok(reverse_success()), ok(refund_success()))
        async with async_client(gateway) as presto:
            init = await presto.payments.init(**WEB_PAY)
            query = await presto.payments.query(presto_mrn=MRN, txn_ref_num="order-123")
            reverse = await presto.payments.reverse(presto_mrn=MRN, payment_ref_num="PP1", reversal_ref_num="rev-1")
            refund = await presto.payments.refund(
                presto_mrn=MRN, payment_ref_num="PP1", refund_ref_num="rf-1", remark="x"
            )
        assert (init.payment_status, query.payment_status, reverse.payment_status, refund.payment_status) == (
            "PendingAuthorise",
            "Expired",
            "Cancelled",
            "PartialRefunded",
        )

    @pytest.mark.anyio
    async def test_validation_is_shared(self) -> None:
        async with async_client(Gateway()) as presto:
            with pytest.raises(PrestoPayConfigError, match="redirect_url"):
                await presto.payments.init(**(WEB_PAY | {"redirect_url": None}))


class TestRaw:
    def test_post_signs_sends_verifies_and_returns_the_body(self) -> None:
        gateway = Gateway(ok(raw_success(somethingNew="yes")))
        with sync_client(gateway) as presto:
            body = presto.raw.post("/v1/ext/payment/something-new", {"prestoMrn": MRN, "flag": True})
        assert body["somethingNew"] == "yes"
        assert verifies_as_merchant(gateway.bodies()[0])

    @pytest.mark.parametrize("path", ["/v2/ext/x", "https://evil.example/v1/ext/x", "/v1/ext/../admin", "/v1/ext/"])
    def test_path_must_stay_under_v1_ext(self, path: str) -> None:
        with sync_client(Gateway()) as presto, pytest.raises(PrestoPayConfigError, match="gateway path"):
            presto.raw.post(path, {"prestoMrn": MRN})

    def test_sdk_owned_fields_are_refused(self) -> None:
        with sync_client(Gateway()) as presto, pytest.raises(PrestoPayConfigError, match="set by the SDK"):
            presto.raw.post("/v1/ext/payment/query", {"prestoMrn": MRN, "mid": "OTHER"})

    def test_sign_and_verify_body(self) -> None:
        with sync_client(Gateway()) as presto:
            signature = presto.raw.sign("1201:Invalid input.:false:20260924124938.038")
            error = business_error("1201", "Invalid input.", ts="20260924124938.038")
            signed = json.dumps(error | {"signature": signature})
            assert presto.raw.verify_body(signed)["errorCode"] == "1201"
            with pytest.raises(PrestoPaySignatureError):
                presto.raw.verify_body(signed.replace("Invalid input.", "Tampered"))
            with pytest.raises(PrestoPayResponseError):
                presto.raw.verify_body(b"[]")
