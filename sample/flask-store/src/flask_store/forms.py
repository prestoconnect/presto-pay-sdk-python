from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from presto_pay import PaymentMethod

MINIMUM_AMOUNT = Decimal("0.01")
MAXIMUM_MINOR_UNITS = 2**31 - 1


@dataclass(frozen=True, slots=True)
class CheckoutForm:
    display_desc: str
    amount_in_ringgit: Decimal
    show_payment_methods: bool
    page_title: str | None
    selected_payment_method: str | None
    receipt_name: str | None
    receipt_email: str | None

    @property
    def amount_minor_units(self) -> int:
        return to_minor_units(self.amount_in_ringgit)

    @classmethod
    def from_json(cls, payload: object) -> tuple[CheckoutForm | None, dict[str, str]]:
        data: dict[str, Any] = payload if isinstance(payload, dict) else {}
        errors: dict[str, str] = {}

        display_desc = _text(data.get("displayDesc"))
        if not display_desc:
            errors["displayDesc"] = "Description is required"
        elif len(display_desc) > 200:
            errors["displayDesc"] = "Description must be at most 200 characters"

        amount = _decimal(data.get("amountInRinggit"))
        if amount is None:
            errors["amountInRinggit"] = "Amount is required"
        elif amount < MINIMUM_AMOUNT:
            errors["amountInRinggit"] = "Amount must be at least 0.01"
        elif to_minor_units(amount) > MAXIMUM_MINOR_UNITS:
            errors["amountInRinggit"] = "Amount is too large"

        show_payment_methods = data.get("showPaymentMethods") is True
        selected_payment_method = _text(data.get("selectedPaymentMethod"))
        if show_payment_methods and not selected_payment_method:
            errors["selectedPaymentMethod"] = "Select a payment method"

        page_title = _text(data.get("pageTitle"))
        receipt_name = _text(data.get("receiptName"))
        receipt_email = _text(data.get("receiptEmail"))
        for field, value, limit in (
            ("pageTitle", page_title, 80),
            ("receiptName", receipt_name, 200),
            ("receiptEmail", receipt_email, 320),
        ):
            if len(value) > limit:
                errors[field] = f"Must be at most {limit} characters"

        if errors or amount is None:
            return None, errors
        form = cls(
            display_desc=display_desc,
            amount_in_ringgit=amount,
            show_payment_methods=show_payment_methods,
            page_title=page_title or None,
            selected_payment_method=selected_payment_method or None,
            receipt_name=receipt_name or None,
            receipt_email=receipt_email or None,
        )
        return form, {}


def default_form() -> dict[str, Any]:
    return {
        "page_title": "MyStore",
        "display_desc": "Checkout demo",
        "amount_in_ringgit": "10.00",
        "show_payment_methods": False,
        "selected_payment_method": PaymentMethod.PM_PG_CARD.value,
        "receipt_name": "",
        "receipt_email": "",
    }


def to_minor_units(amount_in_ringgit: Decimal) -> int:
    return int((amount_in_ringgit * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None
