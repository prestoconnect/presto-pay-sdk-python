from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from mystore.app import create_app
from mystore.config import Settings
from presto_pay import Environment, PrestoPay, RetryReads

KEYS = Path(__file__).resolve().parents[3] / "spec" / "keys"
MID = "PW2401XH9KCX"
MRN = "PM240110XDSFC"
GATEWAY_TS = "20260924133756.056"
NOW = 1790228276.056

SETTINGS = Settings(
    public_base_url="https://shop.example",
    currency="MYR",
    presto_mrn=MRN,
    presto_env={"PRESTOPAY_ENV": "staging", "PRESTOPAY_MID": MID},
)

_KEY = serialization.load_pem_private_key((KEYS / "test-merchant-key.pem").read_bytes(), None)
assert isinstance(_KEY, rsa.RSAPrivateKey)


def signed(body: dict[str, Any]) -> dict[str, Any]:
    def render(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    canonical = ":".join(render(body[key]) for key in sorted(body))
    signature = _KEY.sign(canonical.encode(), padding.PKCS1v15(), hashes.SHA256())
    return {**body, "signature": base64.b64encode(signature).decode()}


class Gateway:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.query_status = "Authorised"
        self.query_details = "[]"
        self.init_error: dict[str, Any] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        self.requests.append({"path": request.url.path, **sent})
        common = {
            "prestoMrn": sent["prestoMrn"],
            "success": True,
            "ts": GATEWAY_TS,
            "errorCode": "",
            "errorMessage": "",
        }
        if request.url.path.endswith("/init"):
            if self.init_error is not None:
                return httpx.Response(200, json=signed(self.init_error))
            body = common | {
                "paymentRefNum": "PP260924K4H3DSF",
                "txnRefNum": sent["txnRefNum"],
                "paymentStatus": "PendingAuthorise",
                "paymentUrl": "https://hpp-staging.prestouniverse.com/PM/PP260924K4H3DSF",
                "amount": sent["amount"],
                "currencyCode": sent["currencyCode"],
            }
        else:
            body = common | {
                "paymentRefNum": "PP260924K4H3DSF",
                "txnRefNum": sent["txnRefNum"],
                "paymentStatus": self.query_status,
                "amount": 123456,
                "currencyCode": "MYR",
                "paymentFinalisedDate": GATEWAY_TS,
                "paymentDetails": self.query_details,
                "refundDetails": "[]",
            }
        return httpx.Response(200, json=signed(body))


class Shop:
    def __init__(self, client: Any, gateway: Gateway) -> None:
        self.client = client
        self.gateway = gateway

    def get(self, path: str) -> tuple[int, str]:
        with self.client.get(path) as response:
            return response.status_code, response.get_data(as_text=True)

    def post_json(self, path: str, payload: object) -> tuple[int, Any]:
        response = self.client.post(path, json=payload)
        return response.status_code, response.get_json()

    def post_raw(self, path: str, body: bytes) -> tuple[int, bytes, str]:
        response = self.client.post(path, data=body, content_type="application/json")
        return response.status_code, response.get_data(), response.headers["Content-Type"]


@pytest.fixture
def shop() -> Shop:
    gateway = Gateway()
    presto = PrestoPay(
        environment=Environment("https://gateway.test"),
        merchant_id=MID,
        private_key=KEYS / "test-merchant-key.pem",
        presto_public_key=KEYS / "test-merchant-cert.pem",
        retry_reads=RetryReads(max_retries=0),
        clock=lambda: NOW,
        http_client=httpx.Client(transport=httpx.MockTransport(gateway)),
    )
    return Shop(create_app(SETTINGS, presto).test_client(), gateway)
