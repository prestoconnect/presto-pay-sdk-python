from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Self

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel
from pydantic_core import PydanticCustomError

MAXIMUM_AMOUNT = Decimal("21474836.47")

_MESSAGES: dict[str, dict[str, str]] = {
    "displayDesc": {
        "string_too_short": "Description is required",
        "string_too_long": "Description must be at most 200 characters",
    },
    "amountInRinggit": {
        "greater_than_equal": "Amount must be at least 0.01",
        "less_than_equal": "Amount is too large",
    },
}
_FALLBACKS = {"displayDesc": "Description is required", "amountInRinggit": "Amount is required"}


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, str_strip_whitespace=True)

    display_desc: str = Field(min_length=1, max_length=200)
    amount_in_ringgit: Decimal = Field(ge=Decimal("0.01"), le=MAXIMUM_AMOUNT)
    show_payment_methods: bool = False
    page_title: str | None = Field(default=None, max_length=80)
    selected_payment_method: str | None = None
    receipt_name: str | None = Field(default=None, max_length=200)
    receipt_email: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def _method_chosen_when_shown(self) -> Self:
        if self.show_payment_methods and not self.selected_payment_method:
            raise PydanticCustomError("payment_method_required", "Select a payment method")
        return self

    @property
    def amount_minor_units(self) -> int:
        return int((self.amount_in_ringgit * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def field_errors(exc: RequestValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for error in exc.errors():
        kind = error["type"]
        location = error["loc"]
        field = location[1] if len(location) > 1 and isinstance(location[1], str) else None
        if kind == "payment_method_required":
            errors.setdefault("selectedPaymentMethod", error["msg"])
        elif field is None:
            for fallback_field, message in _FALLBACKS.items():
                errors.setdefault(fallback_field, message)
        else:
            errors.setdefault(field, _message(field, kind, error))
    return errors


async def validation_failed(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    return JSONResponse(field_errors(exc), status_code=400)


def _message(field: str, kind: str, error: Any) -> str:
    known = _MESSAGES.get(field, {}).get(kind)
    if known:
        return known
    if kind == "string_too_long":
        return f"Must be at most {error['ctx']['max_length']} characters"
    return _FALLBACKS.get(field, error["msg"])
