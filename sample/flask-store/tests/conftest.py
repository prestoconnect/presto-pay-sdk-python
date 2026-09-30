from __future__ import annotations

import httpx
import pytest
from flask import Flask
from flask.testing import FlaskClient
from presto_pay import Environment, PrestoPay, RetryReads

from flask_store import create_app
from flask_store.config import Settings
from tests.support import KEYS, MID, MRN, NOW, Gateway


@pytest.fixture
def gateway() -> Gateway:
    return Gateway()


@pytest.fixture
def app(gateway: Gateway) -> Flask:
    settings = Settings(
        public_base_url="https://shop.example",
        currency="MYR",
        presto_mrn=MRN,
        presto_env={"PRESTOPAY_ENV": "staging", "PRESTOPAY_MID": MID},
    )
    presto = PrestoPay(
        environment=Environment("https://gateway.test"),
        merchant_id=MID,
        private_key=KEYS / "test-merchant-key.pem",
        presto_public_key=KEYS / "test-merchant-cert.pem",
        retry_reads=RetryReads(max_retries=0),
        clock=lambda: NOW,
        http_client=httpx.Client(transport=httpx.MockTransport(gateway)),
    )
    return create_app(settings, presto)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()
