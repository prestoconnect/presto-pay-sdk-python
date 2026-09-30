from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization

from conftest import (
    MID,
    MRN,
    NOW,
    TEST_CERT_PEM,
    TEST_PRIVATE_KEY,
    Gateway,
    async_client,
    business_error,
    client_options,
    raw_success,
    signed_json,
    sync_client,
)
from presto_pay import (
    AsyncPrestoPay,
    NotifyAck,
    PrestoPay,
    PrestoPayApiError,
    PrestoPayConfigError,
    PrestoPayResponseError,
    PrestoPaySignatureError,
    PrestoPayTransportError,
    RetryReads,
    TxnType,
    WebhookOptions,
    WebhookVerifier,
    create_webhook_verifier,
    load_private_key,
)

INIT_PATH = "/v1/ext/payment/init"
QUERY_PATH = "/v1/ext/payment/query"


def _webhook(**overrides: Any) -> bytes:
    body: dict[str, Any] = {
        "eventCode": "Authorised",
        "mid": MID,
        "prestoMrn": MRN,
        "paymentRefNum": "PP1",
        "txnRefNum": "order-123",
        "eventRefNum": "EV1",
        "eventTs": "20260924133756.056",
        "amount": 10000,
        "currencyCode": "MYR",
        "ts": "20260924133756.056",
        "success": True,
    }
    body.update(overrides)
    return signed_json(body)


class TestNotifyAckOnlyStopsRedeliveryForWebhookFailures:
    def test_failed_webhook_verification_is_not_resent(self) -> None:
        verifier = create_webhook_verifier(merchant_id=MID, presto_public_key=TEST_CERT_PEM, clock=lambda: NOW)
        with pytest.raises(PrestoPaySignatureError) as caught:
            verifier.verify(_webhook(mid="PWOTHER"))
        assert NotifyAck.for_error(caught.value) == NotifyAck.OK

    def test_failed_query_inside_the_handler_asks_for_a_resend(self) -> None:
        garbled = httpx.Response(200, content=b"<html>proxy error</html>")
        with sync_client(Gateway(garbled)) as presto, pytest.raises(PrestoPayResponseError) as caught:
            presto.payments.query(presto_mrn=MRN, txn_ref_num="order-123")
        assert caught.value.source == "response"
        assert NotifyAck.for_error(caught.value) == NotifyAck.RESEND

    def test_unsigned_query_response_inside_the_handler_asks_for_a_resend(self) -> None:
        unsigned = httpx.Response(200, content=json.dumps(raw_success()).encode())
        with sync_client(Gateway(unsigned)) as presto, pytest.raises(PrestoPaySignatureError) as caught:
            presto.payments.query(presto_mrn=MRN, txn_ref_num="order-123")
        assert NotifyAck.for_error(caught.value) == NotifyAck.RESEND


class TestWebhookVerifierConstructorValidates:
    def test_single_merchant_id_string_is_not_a_substring_match(self) -> None:
        verifier = WebhookVerifier(merchant_ids="PW2401XH9KCX", presto_public_keys=TEST_CERT_PEM, clock=lambda: NOW)
        assert verifier.merchant_ids == frozenset({"PW2401XH9KCX"})
        for inside in ("PW24", "XH9", "2401"):
            with pytest.raises(PrestoPaySignatureError, match="not a configured merchant ID"):
                verifier.verify(_webhook(mid=inside))
        assert verifier.verify(_webhook()).mid == MID

    @pytest.mark.parametrize("merchant_ids", ["", [], [""]])
    def test_empty_merchant_ids_are_refused(self, merchant_ids: Any) -> None:
        with pytest.raises(PrestoPayConfigError, match="merchant ID"):
            WebhookVerifier(merchant_ids=merchant_ids, presto_public_keys=TEST_CERT_PEM)

    def test_keys_are_loaded_from_any_accepted_input(self) -> None:
        with pytest.raises(PrestoPayConfigError, match="at least one"):
            WebhookVerifier(merchant_ids=MID, presto_public_keys=[])


class TestHttpClientMustMatchTheClientKind:
    def test_sync_client_refuses_an_async_http_client(self) -> None:
        with pytest.raises(PrestoPayConfigError, match=r"needs an httpx\.Client") as caught:
            PrestoPay(**client_options(http_client=httpx.AsyncClient()))
        assert caught.value.field == "http_client"

    def test_async_client_refuses_a_sync_http_client(self) -> None:
        with pytest.raises(PrestoPayConfigError, match=r"needs an httpx\.AsyncClient"):
            AsyncPrestoPay(**client_options(http_client=httpx.Client()))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 0])
def test_deadline_must_be_positive_and_finite(value: float) -> None:
    with pytest.raises(PrestoPayConfigError, match="positive, finite"):
        PrestoPay(**client_options(deadline=value))


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_webhook_window_must_be_finite(value: float) -> None:
    with pytest.raises(PrestoPayConfigError, match="finite"):
        WebhookOptions(max_timestamp_age=value)
    with pytest.raises(PrestoPayConfigError, match="finite"):
        create_webhook_verifier(merchant_id=MID, presto_public_key=TEST_CERT_PEM, max_timestamp_age=value)


def test_backoff_must_be_finite() -> None:
    with pytest.raises(PrestoPayConfigError):
        RetryReads(initial_backoff=float("nan"))
    with pytest.raises(PrestoPayConfigError):
        RetryReads(max_backoff=float("inf"))


class TestWholeCallDeadline:
    def test_sync_response_that_trickles_in_stops_at_the_deadline(self) -> None:
        def trickle() -> Iterator[bytes]:
            for _ in range(20):
                time.sleep(0.1)
                yield b" "

        gateway = Gateway(lambda request: httpx.Response(200, content=trickle()))
        started = time.monotonic()
        with sync_client(gateway, deadline=0.35) as presto, pytest.raises(PrestoPayTransportError) as caught:
            presto.raw.post(INIT_PATH, {"prestoMrn": MRN})
        assert time.monotonic() - started < 1.0
        assert "deadline for the whole call ran out" in str(caught.value)
        assert caught.value.may_have_taken_effect

    @pytest.mark.anyio
    async def test_async_response_that_never_finishes_stops_at_the_deadline(self) -> None:
        async def stall(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5)
            raise AssertionError("unreachable")

        http = httpx.AsyncClient(transport=httpx.MockTransport(stall))
        started = time.monotonic()
        async with async_client(Gateway(), http_client=http, deadline=0.3) as presto:
            with pytest.raises(PrestoPayTransportError) as caught:
                await presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert time.monotonic() - started < 1.0
        assert "deadline for the whole call ran out" in str(caught.value)
        assert not caught.value.may_have_taken_effect


def test_customer_identifiers_are_redacted_from_a_rejected_signature() -> None:
    rejection = httpx.Response(200, content=signed_json(business_error("1006", "Bad")))
    with sync_client(Gateway(rejection)) as presto, pytest.raises(PrestoPayApiError) as caught:
        presto.payments.init(
            presto_mrn=MRN,
            txn_type=TxnType.QR_PAY,
            txn_ref_num="order-123",
            display_desc="Tea",
            qr_value="QR-ONE-TIME-SECRET",
            device_ip="203.0.113.7",
        )
    canonical = caught.value.canonical or ""
    assert "QR-ONE-TIME-SECRET" not in canonical
    assert "203.0.113.7" not in canonical
    assert "[redacted]" in canonical


def test_unencrypted_der_key_loads_even_with_a_password_set() -> None:
    key = serialization.load_pem_private_key(TEST_PRIVATE_KEY.read_bytes(), None)
    der = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    assert load_private_key(der, "shared-password").key_size == 2048
