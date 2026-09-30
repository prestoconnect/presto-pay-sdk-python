from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.support import GATEWAY_TS, HOSTED, SELF_HOSTED, Gateway


def test_checkout_page_renders_the_single_form(client: TestClient) -> None:
    html = client.get("/").text
    for fragment in (
        "MyStore",
        'id="showPaymentMethods"',
        "Continue to Payment",
        "Choose Payment Method",
        'src="/static/js/checkout.js"',
        'value="10.00"',
        'window.CHECKOUT_DEFAULT_SELECTED_METHOD = "PmPgCard"',
    ):
        assert fragment in html
    assert "Recent webhooks" not in html


def test_checkout_javascript_is_served_with_the_payment_method_data(client: TestClient) -> None:
    response = client.get("/static/js/checkout.js")
    assert response.status_code == 200
    assert "TouchNGoEWallet" in response.text


def test_hosted_checkout_lets_presto_offer_every_method(client: TestClient, gateway: Gateway) -> None:
    response = client.post("/checkout", json=HOSTED)
    assert response.status_code == 200
    body = response.json()
    assert body["paymentUrl"].startswith("https://hpp-staging.prestouniverse.com/")
    assert body["txnRefNum"].startswith("demo-")
    (sent,) = gateway.requests
    assert (sent["amount"], sent["txnType"]) == (1000, "WebPay")
    assert sent["notifyUrl"] == "https://shop.example/presto/notify"
    assert sent["redirectUrl"] == f"https://shop.example/return/{body['txnRefNum']}"
    assert "allowedPaymentMethods" not in sent
    assert "receiptEmail" not in sent


def test_self_hosted_checkout_sends_the_chosen_method(client: TestClient, gateway: Gateway) -> None:
    assert client.post("/checkout", json=SELF_HOSTED).status_code == 200
    (sent,) = gateway.requests
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
def test_validation_errors_are_a_field_map(
    client: TestClient, gateway: Gateway, payload: dict[str, object], errors: dict[str, str]
) -> None:
    response = client.post("/checkout", json=payload)
    assert (response.status_code, response.json()) == (400, errors)
    assert gateway.requests == []


def test_gateway_rejection_is_a_502_with_the_error_code(client: TestClient, gateway: Gateway) -> None:
    gateway.init_error = {"success": False, "ts": GATEWAY_TS, "errorCode": "1201", "errorMessage": "Invalid input."}
    response = client.post("/checkout", json=HOSTED)
    assert response.status_code == 502
    body = response.json()
    assert (body["errorCode"], body["errorMessage"], body["mayHaveTakenEffect"]) == ("1201", "Invalid input.", False)
