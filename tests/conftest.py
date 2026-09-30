from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from presto_pay import AsyncPrestoPay, Environment, PrestoPay, RetryReads, load_presto_public_key, load_private_key

SPEC = Path(__file__).resolve().parent.parent / "spec"
KEYS = SPEC / "keys"
VECTORS = SPEC / "vectors"

TEST_PRIVATE_KEY = KEYS / "test-merchant-key.pem"
TEST_PUBLIC_KEY = KEYS / "test-merchant-public.pem"
TEST_CERT_PEM = KEYS / "test-merchant-cert.pem"
TEST_CERT_DER = KEYS / "test-merchant-cert.der"
PRESTO_STAGING_CERT = KEYS / "presto-staging.der"

MID = "PW2401XH9KCX"
MRN = "PM240110XDSFC"
NOW = 1790228276.056
NOW_TS = "20260924133756.056"
BASE_URL = "https://gateway.test"


def load_vectors(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((VECTORS / name).read_text(encoding="utf-8"))
    return loaded


def _test_rsa_key() -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(TEST_PRIVATE_KEY.read_bytes(), None)
    assert isinstance(key, rsa.RSAPrivateKey)
    return key


_GATEWAY_KEY = _test_rsa_key()


def naive_canonical(body: dict[str, Any]) -> str:

    def render(value: Any) -> str:
        if value is None:
            return ""
        if value is True:
            return "true"
        if value is False:
            return "false"
        return str(value)

    return ":".join(render(body[key]) for key in sorted(body) if key != "signature")


def gateway_signature(canonical: str) -> str:
    raw = _GATEWAY_KEY.sign(canonical.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(raw).decode("ascii")


def gateway_sign(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "signature": gateway_signature(naive_canonical(body))}


def signed_json(body: dict[str, Any]) -> bytes:
    return json.dumps(gateway_sign(body), ensure_ascii=False).encode("utf-8")


def verifies_as_merchant(body: dict[str, Any]) -> bool:
    signature = base64.b64decode(body["signature"], validate=True)
    try:
        _GATEWAY_KEY.public_key().verify(
            signature, naive_canonical(body).encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
        )
    except Exception:
        return False
    return True


def business_error(code: str, message: str, ts: str = NOW_TS) -> dict[str, Any]:
    return {"success": False, "ts": ts, "errorCode": code, "errorMessage": message}


def init_success(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "prestoMrn": MRN,
        "paymentRefNum": "PP260924K4H3DSF",
        "txnRefNum": "order-123",
        "paymentStatus": "PendingAuthorise",
        "paymentUrl": "https://hpp-staging.prestouniverse.com/PM/PP260924K4H3DSF",
        "userRefNum": "",
        "amount": 10000,
        "currencyCode": "MYR",
        "paymentRequestDate": NOW_TS,
        "paymentFinalisedDate": "",
        "additionalData": None,
        "success": True,
        "ts": NOW_TS,
        "errorCode": "",
        "errorMessage": "",
    }
    body.update(overrides)
    return body


def ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, content=signed_json(body))


def raw_success(**fields: Any) -> dict[str, Any]:
    return {"prestoMrn": MRN, "success": True, "ts": NOW_TS, "errorCode": "", "errorMessage": "", **fields}


Step = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


class Gateway:
    def __init__(self, *steps: Step) -> None:
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.steps:
            raise AssertionError(f"unexpected request #{len(self.requests)} to {request.url}")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, httpx.Response):
            return step
        return step(request)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests]


_MERCHANT_KEY = load_private_key(TEST_PRIVATE_KEY)
_PRESTO_KEY = load_presto_public_key(TEST_CERT_PEM)


def client_options(**overrides: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "environment": Environment(BASE_URL),
        "merchant_id": MID,
        "private_key": _MERCHANT_KEY,
        "presto_public_key": _PRESTO_KEY,
        "clock": lambda: NOW,
        "retry_reads": RetryReads(initial_backoff=0.0, max_backoff=0.0),
    }
    options.update(overrides)
    return options


def sync_client(gateway: Gateway, **overrides: Any) -> PrestoPay:
    overrides.setdefault("http_client", httpx.Client(transport=httpx.MockTransport(gateway)))
    return PrestoPay(**client_options(**overrides))


def async_client(gateway: Gateway, **overrides: Any) -> AsyncPrestoPay:
    overrides.setdefault("http_client", httpx.AsyncClient(transport=httpx.MockTransport(gateway)))
    return AsyncPrestoPay(**client_options(**overrides))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
