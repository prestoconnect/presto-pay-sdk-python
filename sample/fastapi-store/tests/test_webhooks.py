from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.support import webhook


def _notify(client: TestClient, body: bytes) -> tuple[int, bytes, str]:
    response = client.post("/presto/notify", content=body, headers={"Content-Type": "application/json"})
    return response.status_code, response.content, response.headers["Content-Type"]


def test_verified_webhook_is_listed_once(client: TestClient) -> None:
    assert _notify(client, webhook()) == (200, b'{"resend":false}', "application/json")
    assert _notify(client, webhook())[1] == b'{"resend":false}'
    html = client.get("/").text
    assert "Recent webhooks (shared)" in html
    assert html.count("demo-0123456789abcdef") == 1


def test_forged_webhook_is_acknowledged_but_not_recorded(client: TestClient) -> None:
    forged = json.loads(webhook())
    forged["amount"] = 1
    status, body, _ = _notify(client, json.dumps(forged).encode())
    assert (status, body) == (200, b'{"resend":false}')
    assert "Recent webhooks" not in client.get("/").text


def test_failed_refund_leaves_the_status_unchanged(client: TestClient) -> None:
    assert _notify(client, webhook(eventCode="Refunded", success=False))[1] == b'{"resend":false}'
    html = client.get("/").text
    assert '<td class="px-3 py-2">unchanged</td>' in html
