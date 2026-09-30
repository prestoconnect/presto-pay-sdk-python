from __future__ import annotations

import json

import pytest
from flask.testing import FlaskClient

from tests.support import SELF_HOSTED, Gateway


def test_return_page_shows_the_queried_status(client: FlaskClient, gateway: Gateway) -> None:
    txn_ref_num = client.post("/checkout", json=SELF_HOSTED).get_json()["txnRefNum"]
    gateway.query_details = json.dumps([{"amount": 123456, "method": "Card", "cardSummary": "4111****1111"}])
    html = client.get(f"/return/{txn_ref_num}").get_data(as_text=True)
    for fragment in ("Payment Successful", "RM 1,234.56", "Checkout demo", "Card • 4111****1111", "PP260924K4H3DSF"):
        assert fragment in html
    assert gateway.requests[-1]["txnRefNum"] == txn_ref_num


@pytest.mark.parametrize(
    ("payment_status", "heading"),
    [
        ("PendingAuthorise", "Payment Pending"),
        ("Expired", "Payment Failed"),
        ("PartialRefunded", "Payment PartialRefunded"),
    ],
)
def test_heading_follows_the_status(client: FlaskClient, gateway: Gateway, payment_status: str, heading: str) -> None:
    gateway.query_status = payment_status
    assert heading in client.get("/return/demo-unknown").get_data(as_text=True)


def test_return_without_a_reference_explains_itself(client: FlaskClient) -> None:
    response = client.get("/return")
    assert response.status_code == 200
    assert "/return/demo-abc123" in response.get_data(as_text=True)
