from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from presto_pay._core.canonical import MAX_SAFE_INTEGER, JsonScalar, WireBody, dumps_compact
from presto_pay._core.mapping import to_camel, to_snake
from presto_pay._core.timestamp import format_gateway_timestamp, parse_gateway_timestamp
from presto_pay.errors import Operation, PrestoPayConfigError


@dataclass(frozen=True, slots=True)
class LineItem:
    item_desc: str
    quantity: int
    unit_amount: int
    total_amount: int
    image_url: str | None = None
    item_url: str | None = None
    category: str | None = None
    category_desc: str | None = None
    supplier: str | None = None
    supplier_desc: str | None = None
    supplier_url: str | None = None


class WireFields:
    def __init__(self, operation: Operation, prefix: str = "") -> None:
        self.operation = operation
        self.prefix = prefix
        self.values: WireBody = {}

    def error(self, name: str, message: str) -> PrestoPayConfigError:
        return PrestoPayConfigError(message, field=self.prefix + name, operation=self.operation)

    def label(self, name: str) -> str:
        return self.prefix + name

    def is_set(self, name: str) -> bool:
        return to_camel(name) in self.values

    def text(self, name: str, value: object, *, required: bool = False) -> None:
        if value is None or value == "":
            if required:
                raise self.error(name, f"{self.label(name)} is required")
            return
        self.values[to_camel(name)] = self._checked_text(name, value)

    def amount(self, name: str, value: object, *, required: bool = False, positive: bool = True) -> None:
        if value is None:
            if required:
                raise self.error(name, f"{self.label(name)} is required")
            return
        self.values[to_camel(name)] = self._checked_int(name, value, positive=positive)

    def timestamp(self, name: str, value: datetime | str | None) -> None:
        if value is None:
            return
        if isinstance(value, datetime):
            try:
                self.values[to_camel(name)] = format_gateway_timestamp(value)
            except ValueError as exc:
                raise self.error(name, f"{self.label(name)}: {exc}") from exc
            return
        text = self._checked_text(name, value)
        try:
            parse_gateway_timestamp(text)
        except ValueError as exc:
            raise self.error(
                name, f"{self.label(name)} must be a datetime or a yyyyMMddHHmmss.SSS string: {exc}"
            ) from exc
        self.values[to_camel(name)] = text

    def codes(self, name: str, value: Sequence[str] | None) -> None:
        if value is None:
            return
        items = self._checked_sequence(name, value)
        self.values[to_camel(name)] = dumps_compact(
            [self._checked_text(f"{name}[{index}]", item) for index, item in enumerate(items)]
        )

    def line_items(self, name: str, value: Sequence[LineItem] | None) -> None:
        if value is None:
            return
        items = self._checked_sequence(name, value)
        self.values[to_camel(name)] = dumps_compact(
            [self._line_item(f"{name}[{index}]", item) for index, item in enumerate(items)]
        )

    def _line_item(self, name: str, item: object) -> Mapping[str, JsonScalar]:
        if not isinstance(item, LineItem):
            raise self.error(name, f"{self.label(name)} must be a LineItem, not {type(item).__name__}")
        nested = WireFields(self.operation, prefix=f"{self.label(name)}.")
        nested.text("item_desc", item.item_desc, required=True)
        nested.amount("quantity", item.quantity, required=True)
        nested.amount("unit_amount", item.unit_amount, required=True, positive=False)
        nested.amount("total_amount", item.total_amount, required=True, positive=False)
        for optional in (
            "image_url",
            "item_url",
            "category",
            "category_desc",
            "supplier",
            "supplier_desc",
            "supplier_url",
        ):
            nested.text(optional, getattr(item, optional))
        return nested.values

    def _checked_text(self, name: str, value: object) -> str:
        if not isinstance(value, str):
            raise self.error(name, f"{self.label(name)} must be a str, not {type(value).__name__}")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise self.error(
                name, f"{self.label(name)} contains characters that cannot be sent as UTF-8 (an unpaired surrogate)"
            ) from exc
        return str(value)

    def _checked_int(self, name: str, value: object, *, positive: bool) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            kind = type(value).__name__
            raise self.error(
                name, f"{self.label(name)} must be an int in minor currency units (1200 for MYR 12.00), not {kind}"
            )
        if positive and value <= 0:
            raise self.error(name, f"{self.label(name)} must be greater than 0")
        if abs(value) > MAX_SAFE_INTEGER:
            raise self.error(name, f"{self.label(name)} is too large")
        return int(value)

    def _checked_sequence(self, name: str, value: object) -> Sequence[object]:
        if isinstance(value, str | bytes) or not isinstance(value, Sequence):
            raise self.error(name, f"{self.label(name)} must be a list, not {type(value).__name__}")
        if not value:
            raise self.error(name, f"{self.label(name)} must not be empty; leave it out instead")
        return value


def check_documented_lengths(
    fields: Mapping[str, JsonScalar], lengths: Mapping[str, int], operation: Operation
) -> None:
    for wire_name, limit in lengths.items():
        value = fields.get(wire_name)
        if isinstance(value, str) and len(value) > limit:
            name = to_snake(wire_name)
            raise PrestoPayConfigError(
                f"{name} is {len(value)} characters; the documented maximum is {limit} (strict mode)",
                field=name,
                operation=operation,
            )
