from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from tests.support import Gateway, webhook


def _notify(client: TestClient, body: bytes) -> tuple[int, bytes, str]:
    response = client.post("/presto/notify", content=body, headers={"Content-Type": "application/json"})
    return response.status_code, response.content, response.headers["Content-Type"]


def test_redelivery_is_acknowledged_without_fulfilling_again(
    client: TestClient, gateway: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    assert _notify(client, webhook()) == (200, b'{"resend":false}', "application/json")
    assert _notify(client, webhook())[1] == b'{"resend":false}'
    assert "Recent webhooks (shared)" in client.get("/").text
    assert len(gateway.requests) == 2
    assert caplog.text.count("paid; fulfilling it") == 1
    assert "already finalised; Authorised changes nothing" in caplog.text


def test_later_refund_applies_but_a_stale_status_does_not(
    client: TestClient, gateway: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    _notify(client, webhook())
    gateway.query_status = "Refunded"
    _notify(client, webhook(eventCode="Refunded"))
    gateway.query_status = "Authorised"
    _notify(client, webhook())
    assert "is now Refunded" in caplog.text
    assert "already finalised; Authorised changes nothing" in caplog.text
    assert caplog.text.count("paid; fulfilling it") == 1


def test_status_comes_from_querying_the_payment(client: TestClient, gateway: Gateway) -> None:
    gateway.query_status = "PartialRefunded"
    _notify(client, webhook(eventCode="Refunded", success=False))
    (query,) = gateway.requests
    assert query["path"].endswith("/query")
    assert query["paymentRefNum"] == "PP260924K4H3DSF"
    assert '<td class="px-3 py-2">PartialRefunded</td>' in client.get("/").text


def test_failed_query_asks_presto_to_resend(client: TestClient, gateway: Gateway) -> None:
    gateway.query_http_status = 503
    assert _notify(client, webhook())[1] == b'{"resend":true}'
    assert "Recent webhooks" not in client.get("/").text


def test_forged_webhook_is_rejected_with_401_and_not_recorded(client: TestClient, gateway: Gateway) -> None:
    forged = json.loads(webhook())
    forged["amount"] = 1
    status, body, _ = _notify(client, json.dumps(forged).encode())
    assert (status, body) == (401, b"")
    assert "Recent webhooks" not in client.get("/").text
    assert gateway.requests == []
