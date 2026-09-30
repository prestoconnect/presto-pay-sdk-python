from __future__ import annotations

from decimal import Decimal

import pytest

from flask_store.forms import CheckoutForm, to_minor_units


def test_amount_conversion_rounds_half_up() -> None:
    assert to_minor_units(Decimal("10.005")) == 1001
    assert to_minor_units(Decimal("0.01")) == 1


@pytest.mark.parametrize("payload", [None, [], "text"])
def test_non_object_payload_is_a_validation_error(payload: object) -> None:
    form, errors = CheckoutForm.from_json(payload)
    assert form is None
    assert set(errors) == {"displayDesc", "amountInRinggit"}


@pytest.mark.parametrize("amount", ["abc", "NaN", "Infinity", True, "99999999", "1e30", "1e999999"])
def test_unusable_amounts_are_rejected(amount: object) -> None:
    form, errors = CheckoutForm.from_json({"displayDesc": "x", "amountInRinggit": amount})
    assert form is None
    assert "amountInRinggit" in errors
