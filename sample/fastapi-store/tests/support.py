from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

KEYS = Path(__file__).resolve().parents[3] / "spec" / "keys"
MID = "PW2401XH9KCX"
MRN = "PM240110XDSFC"
GATEWAY_TS = "20260924133756.056"
NOW = 1790228276.056

HOSTED = {
    "displayDesc": "Checkout demo",
    "amountInRinggit": "10.00",
    "showPaymentMethods": False,
    "pageTitle": "MyStore",
}
SELF_HOSTED = HOSTED | {
    "showPaymentMethods": True,
    "selectedPaymentMethod": "TouchNGoEWallet",
    "receiptName": "Aisyah",
    "receiptEmail": "aisyah@example.com",
}

_KEY = serialization.load_pem_private_key((KEYS / "test-merchant-key.pem").read_bytes(), None)
if not isinstance(_KEY, rsa.RSAPrivateKey):
    raise TypeError("the spec test key must be RSA")


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


def webhook(**overrides: object) -> bytes:
    body: dict[str, Any] = {
        "eventCode": "Authorised",
        "mid": MID,
        "prestoMrn": MRN,
        "paymentRefNum": "PP260924K4H3DSF",
        "txnRefNum": "demo-0123456789abcdef",
        "eventRefNum": "EV1",
        "eventTs": GATEWAY_TS,
        "amount": 1000,
        "currencyCode": "MYR",
        "ts": GATEWAY_TS,
        "success": True,
    }
    body.update(overrides)
    return json.dumps(signed(body)).encode()


class Gateway:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.query_status = "Authorised"
        self.query_details = "[]"
        self.init_error: dict[str, Any] | None = None
        self.query_http_status = 200

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
            if self.query_http_status != 200:
                return httpx.Response(self.query_http_status)
            body = common | {
                "paymentRefNum": sent.get("paymentRefNum", "PP260924K4H3DSF"),
                "txnRefNum": sent.get("txnRefNum", "demo-0123456789abcdef"),
                "paymentStatus": self.query_status,
                "amount": 123456,
                "currencyCode": "MYR",
                "paymentFinalisedDate": GATEWAY_TS,
                "paymentDetails": self.query_details,
                "refundDetails": "[]",
            }
        return httpx.Response(200, json=signed(body))
