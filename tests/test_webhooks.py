from __future__ import annotations

import json
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from conftest import (
    MID,
    MRN,
    NOW,
    NOW_TS,
    TEST_CERT_PEM,
    Gateway,
    async_client,
    gateway_sign,
    signed_json,
    sync_client,
)
from presto_pay import (
    NotifyAck,
    PaymentStatus,
    PrestoPayConfigError,
    PrestoPayResponseError,
    PrestoPaySignatureError,
    WebhookOptions,
    WebhookVerifier,
    create_webhook_verifier,
)


def webhook(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "eventCode": "Authorised",
        "mid": MID,
        "prestoMrn": MRN,
        "paymentRefNum": "PP1",
        "txnRefNum": "order-123",
        "eventRefNum": "EV1",
        "eventTs": NOW_TS,
        "amount": 10000,
        "currencyCode": "MYR",
        "ts": NOW_TS,
        "success": True,
        "userRefNum": None,
        "additionalData": "",
        "paymentDetails": "[]",
    }
    body.update(overrides)
    return body


def verifier(now: float = NOW, **options: Any) -> WebhookVerifier:
    settings: dict[str, Any] = {"merchant_id": MID, "presto_public_key": TEST_CERT_PEM, "clock": lambda: now}
    settings.update(options)
    return create_webhook_verifier(**settings)


class TestAccepted:
    @pytest.mark.parametrize("encode", [bytes, lambda raw: raw.decode("utf-8"), bytearray, memoryview])
    def test_raw_body_in_any_buffer(self, encode: Any) -> None:
        event = verifier().verify(encode(signed_json(webhook())))
        assert (event.mid, event.event_ref_num, event.amount, event.success) == (MID, "EV1", 10000, True)
        assert event.user_ref_num is None
        assert event.additional_data is None
        assert event.payment_details == ()

    @pytest.mark.parametrize(
        ("event_code", "success", "status"),
        [
            ("Authorised", True, PaymentStatus.AUTHORISED),
            ("Authorised", False, PaymentStatus.FAILED),
            ("Cancelled", True, PaymentStatus.CANCELLED),
            ("Refunded", True, PaymentStatus.REFUNDED),
            ("Refunded", False, None),
            ("Reversed", True, PaymentStatus.REVERSED),
            ("Reversed", False, None),
            ("Cancelled", False, PaymentStatus.CANCELLED),
            ("Expired", False, PaymentStatus.EXPIRED),
            ("SomethingNew", True, "SomethingNew"),
        ],
    )
    def test_derived_payment_status(self, event_code: str, success: bool, status: str | None) -> None:
        event = verifier().verify(signed_json(webhook(eventCode=event_code, success=success)))
        assert event.payment_status == status

    def test_payment_details(self) -> None:
        details = json.dumps([{"amount": 10000, "method": "Wallet"}])
        event = verifier().verify(signed_json(webhook(paymentDetails=details)))
        assert event.payment_details[0].method == "Wallet"

    def test_redelivery_carries_a_fresh_ts_and_the_same_event_ref_num(self) -> None:
        first = verifier(now=NOW).verify(signed_json(webhook()))
        later_ts = "20260924135556.056"
        second = verifier(now=NOW + 18 * 60).verify(signed_json(webhook(ts=later_ts)))
        assert first.event_ref_num == second.event_ref_num

    def test_one_endpoint_for_several_merchants_reports_which_matched(self) -> None:
        several = verifier(merchant_id={MID, "PWOTHER"})
        assert several.verify(signed_json(webhook(mid="PWOTHER"))).mid == "PWOTHER"
        assert several.verify(signed_json(webhook())).mid == MID

    def test_key_rotation_tries_each_key(self) -> None:
        retired = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
        retired_pem = retired.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        rotating = verifier(presto_public_key=[retired_pem, TEST_CERT_PEM])
        assert rotating.verify(signed_json(webhook())).mid == MID

    def test_freshness_boundary_and_opt_out(self) -> None:
        verifier(now=NOW + 15 * 60).verify(signed_json(webhook()))
        verifier(now=NOW - 15 * 60).verify(signed_json(webhook()))
        verifier(now=NOW + 86400, max_timestamp_age=None).verify(signed_json(webhook()))


class TestRejected:
    def test_parsed_dict_is_refused_with_framework_hints(self) -> None:
        with pytest.raises(PrestoPayConfigError, match=r"request\.get_data\(\)") as caught:
            verifier().verify(webhook())  # type: ignore[arg-type]
        assert caught.value.operation == "webhook"
        assert "await request.body()" in str(caught.value)

    def test_malformed_body(self) -> None:
        with pytest.raises(PrestoPayResponseError) as caught:
            verifier().verify(b"not json")
        assert caught.value.source == "webhook"
        assert NotifyAck.for_error(caught.value) == NotifyAck.OK

    def test_missing_signature(self) -> None:
        with pytest.raises(PrestoPaySignatureError, match="no signature"):
            verifier().verify(json.dumps(webhook()).encode())

    def test_tampered_body(self) -> None:
        tampered = gateway_sign(webhook()) | {"amount": 1}
        with pytest.raises(PrestoPaySignatureError, match="does not verify") as caught:
            verifier().verify(json.dumps(tampered).encode())
        assert NotifyAck.for_error(caught.value) == NotifyAck.OK

    def test_signature_from_the_shared_key_for_another_merchant(self) -> None:
        with pytest.raises(PrestoPaySignatureError, match="not a configured merchant ID"):
            verifier().verify(signed_json(webhook(mid="PWSOMEONEELSE")))

    @pytest.mark.parametrize("offset", [15 * 60 + 1, -(15 * 60 + 1)])
    def test_stale_or_future_ts(self, offset: float) -> None:
        with pytest.raises(PrestoPaySignatureError, match=r"outside the 900s window") as caught:
            verifier(now=NOW + offset).verify(signed_json(webhook()))
        assert NOW_TS in str(caught.value)

    def test_configurable_window(self) -> None:
        with pytest.raises(PrestoPaySignatureError, match="outside the 60s window"):
            verifier(now=NOW + 61, max_timestamp_age=60).verify(signed_json(webhook()))

    @pytest.mark.parametrize("missing", ["eventRefNum", "eventCode", "amount", "ts", "success"])
    def test_missing_required_field(self, missing: str) -> None:
        body = webhook()
        del body[missing]
        with pytest.raises(PrestoPayResponseError, match=missing):
            verifier().verify(signed_json(body))

    def test_malformed_ts(self) -> None:
        with pytest.raises(PrestoPayResponseError, match="gateway timestamp"):
            verifier().verify(signed_json(webhook(ts="2026-09-24T13:37:56")))

    def test_error_bodies_are_redacted(self) -> None:
        details = json.dumps([{"amount": 1, "cardBin": "411111"}])
        body = webhook(paymentDetails=details)
        del body["eventRefNum"]
        with pytest.raises(PrestoPayResponseError) as caught:
            verifier().verify(signed_json(body))
        assert "411111" not in (caught.value.raw_body or "")


class TestConfiguration:
    @pytest.mark.parametrize("merchant_id", ["", set(), {""}])
    def test_needs_merchant_ids(self, merchant_id: Any) -> None:
        with pytest.raises(PrestoPayConfigError, match="merchant ID"):
            verifier(merchant_id=merchant_id)

    @pytest.mark.parametrize("age", [0, -1, True])
    def test_window_must_be_positive(self, age: Any) -> None:
        with pytest.raises(PrestoPayConfigError, match="max_timestamp_age"):
            verifier(max_timestamp_age=age)
        with pytest.raises(PrestoPayConfigError, match="max_timestamp_age"):
            WebhookOptions(max_timestamp_age=age)


class TestNotifyAck:
    def test_reply_bodies(self) -> None:
        assert json.loads(NotifyAck.OK) == {"resend": False}
        assert json.loads(NotifyAck.RESEND) == {"resend": True}
        assert NotifyAck.CONTENT_TYPE == "application/json"

    def test_merchant_side_failures_ask_for_a_resend(self) -> None:
        assert NotifyAck.for_error(ConnectionError("database down")) == NotifyAck.RESEND


class TestClientWebhooks:
    def test_sync_client_verifies_for_its_own_merchant(self) -> None:
        with sync_client(Gateway()) as presto:
            assert presto.webhooks.verify(signed_json(webhook())).mid == MID
            with pytest.raises(PrestoPaySignatureError):
                presto.webhooks.verify(signed_json(webhook(mid="PWOTHER")))

    @pytest.mark.anyio
    async def test_async_client_verification_is_plain_sync(self) -> None:
        async with async_client(Gateway()) as presto:
            assert presto.webhooks.verify(signed_json(webhook())).event_ref_num == "EV1"

    def test_client_webhook_window_is_configurable(self) -> None:
        with sync_client(Gateway(), webhooks=WebhookOptions(max_timestamp_age=None), clock=lambda: NOW + 3600) as p:
            assert p.webhooks.verify(signed_json(webhook())).mid == MID
