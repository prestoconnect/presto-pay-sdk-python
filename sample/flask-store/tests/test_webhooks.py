from __future__ import annotations

import json

from flask.testing import FlaskClient

from tests.support import webhook


def _notify(client: FlaskClient, body: bytes) -> tuple[int, bytes, str]:
    response = client.post("/presto/notify", data=body, content_type="application/json")
    return response.status_code, response.get_data(), response.headers["Content-Type"]


def test_verified_webhook_is_listed_once(client: FlaskClient) -> None:
    assert _notify(client, webhook()) == (200, b'{"resend":false}', "application/json")
    assert _notify(client, webhook())[1] == b'{"resend":false}'
    html = client.get("/").get_data(as_text=True)
    assert "Recent webhooks (shared)" in html
    assert html.count("demo-0123456789abcdef") == 1


def test_forged_webhook_is_acknowledged_but_not_recorded(client: FlaskClient) -> None:
    forged = json.loads(webhook())
    forged["amount"] = 1
    status, body, _ = _notify(client, json.dumps(forged).encode())
    assert (status, body) == (200, b'{"resend":false}')
    assert "Recent webhooks" not in client.get("/").get_data(as_text=True)


def test_failed_refund_leaves_the_status_unchanged(client: FlaskClient) -> None:
    assert _notify(client, webhook(eventCode="Refunded", success=False))[1] == b'{"resend":false}'
    html = client.get("/").get_data(as_text=True)
    assert '<td class="px-3 py-2">unchanged</td>' in html
