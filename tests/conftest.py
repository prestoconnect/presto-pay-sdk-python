from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

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
    """A second, deliberately simple canonicalizer, so tests do not sign mock responses with the code under test."""

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
