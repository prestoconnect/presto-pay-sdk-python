from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from fastapi_store.schemas import CheckoutRequest


def test_amount_conversion_rounds_half_up() -> None:
    request = CheckoutRequest(display_desc="x", amount_in_ringgit=Decimal("10.005"))
    assert request.amount_minor_units == 1001


def test_camel_case_json_maps_onto_snake_case_fields() -> None:
    request = CheckoutRequest.model_validate({"displayDesc": " Tea ", "amountInRinggit": "1.50", "pageTitle": "T"})
    assert (request.display_desc, request.amount_in_ringgit, request.page_title) == ("Tea", Decimal("1.50"), "T")


@pytest.mark.parametrize("body", [b"not json", b"null", b"[]", b""])
def test_non_object_body_is_a_field_map_not_a_422(client: TestClient, body: bytes) -> None:
    response = client.post("/checkout", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert set(response.json()) == {"displayDesc", "amountInRinggit"}


@pytest.mark.parametrize(
    ("amount", "message"),
    [
        ("abc", "Amount is required"),
        ("NaN", "Amount is required"),
        ("99999999", "Amount is too large"),
    ],
)
def test_unusable_amounts_are_rejected(client: TestClient, amount: str, message: str) -> None:
    response = client.post("/checkout", json={"displayDesc": "x", "amountInRinggit": amount})
    assert (response.status_code, response.json()) == (400, {"amountInRinggit": message})


def test_long_optional_field_reports_its_limit(client: TestClient) -> None:
    response = client.post("/checkout", json={"displayDesc": "x", "amountInRinggit": "1", "pageTitle": "t" * 81})
    assert response.json() == {"pageTitle": "Must be at most 80 characters"}
