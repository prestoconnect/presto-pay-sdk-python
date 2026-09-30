from __future__ import annotations

import json
from decimal import Decimal

import pytest

from conftest import GATEWAY_TS, MID, MRN, Shop, signed
from mystore.checkout import parse_checkout, to_minor_units

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


def webhook(**overrides: object) -> bytes:
    body = {
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


def test_checkout_page_renders_the_single_form(shop: Shop) -> None:
    status, html = shop.get("/")
    assert status == 200
    for fragment in (
        "MyStore",
        'id="showPaymentMethods"',
        "Continue to Payment",
        "Choose Payment Method",
        'src="/js/checkout.js"',
        'value="10.00"',
        'window.CHECKOUT_DEFAULT_SELECTED_METHOD = "PmPgCard"',
    ):
        assert fragment in html
    assert "Recent webhooks" not in html


def test_checkout_javascript_is_served_with_the_payment_method_data(shop: Shop) -> None:
    status, script = shop.get("/js/checkout.js")
    assert status == 200
    assert "PmPgCard" in script
    assert "TouchNGoEWallet" in script


def test_hosted_checkout_lets_presto_offer_every_method(shop: Shop) -> None:
    status, body = shop.post_json("/checkout", HOSTED)
    assert status == 200
    assert body["paymentUrl"].startswith("https://hpp-staging.prestouniverse.com/")
    assert body["txnRefNum"].startswith("demo-")
    (sent,) = shop.gateway.requests
    assert sent["amount"] == 1000
    assert sent["txnType"] == "WebPay"
    assert sent["notifyUrl"] == "https://shop.example/presto/notify"
    assert sent["redirectUrl"] == f"https://shop.example/return/{body['txnRefNum']}"
    assert "allowedPaymentMethods" not in sent
    assert "receiptEmail" not in sent


def test_self_hosted_checkout_sends_the_chosen_method(shop: Shop) -> None:
    status, _ = shop.post_json("/checkout", SELF_HOSTED)
    assert status == 200
    (sent,) = shop.gateway.requests
    assert sent["allowedPaymentMethods"] == '["TouchNGoEWallet"]'
    assert (sent["receiptName"], sent["receiptEmail"]) == ("Aisyah", "aisyah@example.com")


@pytest.mark.parametrize(
    ("payload", "errors"),
    [
        (HOSTED | {"amountInRinggit": None}, {"amountInRinggit": "Amount is required"}),
        (HOSTED | {"amountInRinggit": "0.001"}, {"amountInRinggit": "Amount must be at least 0.01"}),
        (HOSTED | {"displayDesc": "  "}, {"displayDesc": "Description is required"}),
        (SELF_HOSTED | {"selectedPaymentMethod": None}, {"selectedPaymentMethod": "Select a payment method"}),
    ],
)
def test_validation_errors_are_a_field_map(shop: Shop, payload: dict[str, object], errors: dict[str, str]) -> None:
    assert shop.post_json("/checkout", payload) == (400, errors)
    assert shop.gateway.requests == []


def test_gateway_rejection_is_a_502_with_the_error_code(shop: Shop) -> None:
    shop.gateway.init_error = {
        "success": False,
        "ts": GATEWAY_TS,
        "errorCode": "1201",
        "errorMessage": "Invalid input.",
    }
    status, body = shop.post_json("/checkout", HOSTED)
    assert status == 502
    assert (body["errorCode"], body["errorMessage"], body["mayHaveTakenEffect"]) == ("1201", "Invalid input.", False)


def test_return_page_shows_the_queried_status(shop: Shop) -> None:
    _, created = shop.post_json("/checkout", SELF_HOSTED)
    shop.gateway.query_details = json.dumps([{"amount": 123456, "method": "Card", "cardSummary": "4111****1111"}])
    status, html = shop.get(f"/return/{created['txnRefNum']}")
    assert status == 200
    for fragment in ("Payment Successful", "RM 1,234.56", "Checkout demo", "Card • 4111****1111", "PP260924K4H3DSF"):
        assert fragment in html
    assert shop.gateway.requests[-1]["txnRefNum"] == created["txnRefNum"]


@pytest.mark.parametrize(
    ("payment_status", "heading"),
    [
        ("PendingAuthorise", "Payment Pending"),
        ("Expired", "Payment Failed"),
        ("PartialRefunded", "Payment PartialRefunded"),
    ],
)
def test_return_page_heading_follows_the_status(shop: Shop, payment_status: str, heading: str) -> None:
    shop.gateway.query_status = payment_status
    assert heading in shop.get("/return/demo-unknown")[1]


def test_return_without_a_reference_explains_itself(shop: Shop) -> None:
    status, html = shop.get("/return")
    assert status == 200
    assert "/return/demo-abc123" in html


def test_verified_webhook_is_listed_once(shop: Shop) -> None:
    assert shop.post_raw("/presto/notify", webhook()) == (200, b'{"resend":false}', "application/json")
    assert shop.post_raw("/presto/notify", webhook(ts=GATEWAY_TS))[1] == b'{"resend":false}'
    html = shop.get("/")[1]
    assert "Recent webhooks (shared)" in html
    assert html.count("demo-0123456789abcdef") == 1


def test_forged_webhook_is_acknowledged_but_not_recorded(shop: Shop) -> None:
    forged = json.loads(webhook())
    forged["amount"] = 1
    status, body, _ = shop.post_raw("/presto/notify", json.dumps(forged).encode())
    assert (status, body) == (200, b'{"resend":false}')
    assert "Recent webhooks" not in shop.get("/")[1]


def test_amount_conversion_rounds_half_up() -> None:
    assert to_minor_units(Decimal("10.005")) == 1001
    assert to_minor_units(Decimal("0.01")) == 1


def test_non_json_payload_is_a_validation_error() -> None:
    form, errors = parse_checkout(None)
    assert form is None
    assert set(errors) == {"displayDesc", "amountInRinggit"}
