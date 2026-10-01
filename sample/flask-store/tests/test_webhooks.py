from __future__ import annotations

import json

from flask.testing import FlaskClient

from tests.support import Gateway, webhook


def _notify(client: FlaskClient, body: bytes) -> tuple[int, bytes, str]:
    response = client.post("/presto/notify", data=body, content_type="application/json")
    return response.status_code, response.get_data(), response.headers["Content-Type"]


def test_verified_webhook_is_listed_once(client: FlaskClient, gateway: Gateway) -> None:
    assert _notify(client, webhook()) == (200, b'{"resend":false}', "application/json")
    assert _notify(client, webhook())[1] == b'{"resend":false}'
    html = client.get("/").get_data(as_text=True)
    assert "Recent webhooks (shared)" in html
    assert html.count("demo-0123456789abcdef") == 1
    assert len(gateway.requests) == 1


def test_status_comes_from_querying_the_payment(client: FlaskClient, gateway: Gateway) -> None:
    gateway.query_status = "PartialRefunded"
    _notify(client, webhook(eventCode="Refunded", success=False))
    (query,) = gateway.requests
    assert query["path"].endswith("/query")
    assert query["paymentRefNum"] == "PP260924K4H3DSF"
    assert '<td class="px-3 py-2">PartialRefunded</td>' in client.get("/").get_data(as_text=True)


def test_failed_query_asks_presto_to_resend(client: FlaskClient, gateway: Gateway) -> None:
    gateway.query_http_status = 503
    assert _notify(client, webhook())[1] == b'{"resend":true}'
    assert "Recent webhooks" not in client.get("/").get_data(as_text=True)


def test_forged_webhook_is_rejected_with_401_and_not_recorded(client: FlaskClient, gateway: Gateway) -> None:
    forged = json.loads(webhook())
    forged["amount"] = 1
    status, body, _ = _notify(client, json.dumps(forged).encode())
    assert (status, body) == (401, b"")
    assert "Recent webhooks" not in client.get("/").get_data(as_text=True)
    assert gateway.requests == []
