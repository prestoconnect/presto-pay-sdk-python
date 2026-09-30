from __future__ import annotations

import httpx
import pytest

from conftest import MRN, Gateway, async_client, ok, raw_success, sync_client
from presto_pay import JsonScalar


def _wire(request: httpx.Request) -> tuple[str, str, bytes, list[tuple[str, str]]]:
    headers = sorted((k.lower(), v) for k, v in request.headers.items() if k.lower() in {"content-type", "user-agent"})
    return request.method, str(request.url), request.content, headers


@pytest.mark.anyio
async def test_raw_post_sends_identical_bytes_sync_and_async() -> None:
    body: dict[str, JsonScalar] = {"prestoMrn": MRN, "txnRefNum": "order-123", "displayDesc": "Café", "amount": 1200}
    sync_gateway = Gateway(ok(raw_success()))
    async_gateway = Gateway(ok(raw_success()))

    with sync_client(sync_gateway) as presto:
        sync_result = presto.raw.post("/v1/ext/payment/init", body)
    async with async_client(async_gateway) as presto_async:
        async_result = await presto_async.raw.post("/v1/ext/payment/init", body)

    assert _wire(sync_gateway.requests[0]) == _wire(async_gateway.requests[0])
    assert sync_result == async_result
