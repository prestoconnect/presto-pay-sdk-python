from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from conftest import MRN, Gateway, async_client, init_success, ok, raw_success, sync_client
from presto_pay import JsonScalar, LineItem, PaymentMethod, TxnType


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


@pytest.mark.anyio
async def test_every_payment_operation_sends_identical_bytes_sync_and_async() -> None:
    calls: list[tuple[str, dict[str, Any]]] = [
        (
            "init",
            {
                "presto_mrn": MRN,
                "txn_type": TxnType.WEB_PAY,
                "txn_ref_num": "order-123",
                "display_desc": "Order 123 — café",
                "amount": 10_000,
                "currency_code": "MYR",
                "redirect_url": "https://shop.example/return",
                "allowed_payment_methods": [PaymentMethod.WALLET, PaymentMethod.CARD],
                "item_list": [LineItem(item_desc="Tea", quantity=2, unit_amount=500, total_amount=1000)],
                "session_validity": datetime(2026, 9, 24, 6, 0, tzinfo=UTC),
            },
        ),
        ("query", {"presto_mrn": MRN, "txn_ref_num": "order-123"}),
        ("reverse", {"presto_mrn": MRN, "payment_ref_num": "PP1", "reversal_ref_num": "rev-1"}),
        ("refund", {"presto_mrn": MRN, "payment_ref_num": "PP1", "refund_ref_num": "rf-1", "remark": "x"}),
    ]
    responses = [init_success(), raw_success(txnRefNum="order-123", paymentRefNum="PP1")] + [
        raw_success(paymentRefNum="PP1")
    ] * 2
    sync_gateway = Gateway(*[ok(body) for body in responses])
    async_gateway = Gateway(*[ok(body) for body in responses])

    with sync_client(sync_gateway) as presto:
        for name, kwargs in calls:
            getattr(presto.payments, name)(**kwargs)
    async with async_client(async_gateway) as presto_async:
        for name, kwargs in calls:
            await getattr(presto_async.payments, name)(**kwargs)

    for sync_request, async_request in zip(sync_gateway.requests, async_gateway.requests, strict=True):
        assert _wire(sync_request) == _wire(async_request)
