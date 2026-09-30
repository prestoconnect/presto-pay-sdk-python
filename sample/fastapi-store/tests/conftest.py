from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from presto_pay import AsyncPrestoPay, Environment, RetryReads

from fastapi_store.config import Settings
from fastapi_store.main import create_app
from tests.support import KEYS, MID, MRN, NOW, Gateway


@pytest.fixture
def gateway() -> Gateway:
    return Gateway()


@pytest.fixture
def client(gateway: Gateway) -> Iterator[TestClient]:
    settings = Settings(
        public_base_url="https://shop.example",
        currency="MYR",
        presto_mrn=MRN,
        presto_env={"PRESTOPAY_ENV": "staging", "PRESTOPAY_MID": MID},
    )
    presto = AsyncPrestoPay(
        environment=Environment("https://gateway.test"),
        merchant_id=MID,
        private_key=KEYS / "test-merchant-key.pem",
        presto_public_key=KEYS / "test-merchant-cert.pem",
        retry_reads=RetryReads(max_retries=0),
        clock=lambda: NOW,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(gateway)),
    )
    with TestClient(create_app(settings, presto)) as test_client:
        yield test_client
