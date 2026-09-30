from __future__ import annotations

import re
from collections.abc import Mapping

from presto_pay._core.canonical import BodyError, JsonScalar, WireBody, as_scalar, loads_strict, render_value

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")
_INTEGER_TEXT = re.compile(r"-?[0-9]{1,16}")


class MappingError(ValueError):
    pass


def to_camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def to_snake(name: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", name).lower()


class FieldReader:
    __slots__ = ("_body", "_strict")

    def __init__(self, body: Mapping[str, JsonScalar], *, strict: bool) -> None:
        self._body = body
        self._strict = strict

    @property
    def body(self) -> Mapping[str, JsonScalar]:
        return self._body

    def optional_str(self, key: str) -> str | None:
        value = self._body.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return value
        # The gateway documents these fields as strings; a stray number or boolean on an authentic body is
        # tolerated as text unless strict mode asks for the contract violation to surface.
        if self._strict:
            raise MappingError(f"{key} should be a string, got {type(value).__name__}")
        return render_value(value)

    def required_str(self, key: str) -> str:
        value = self.optional_str(key)
        if value is None:
            raise MappingError(f"required field {key} is missing or empty")
        return value

    def optional_int(self, key: str) -> int | None:
        value = self._body.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise MappingError(f"{key} should be an integer, got a boolean")
        if isinstance(value, int):
            return value
        if not self._strict and _INTEGER_TEXT.fullmatch(value):
            return int(value)
        raise MappingError(f"{key} should be an integer, got {value!r}")

    def required_int(self, key: str) -> int:
        value = self.optional_int(key)
        if value is None:
            raise MappingError(f"required field {key} is missing or empty")
        return value

    def required_bool(self, key: str) -> bool:
        value = self._body.get(key)
        if not isinstance(value, bool):
            raise MappingError(f"{key} should be a boolean, got {type(value).__name__}")
        return value

    def list_of_objects(self, key: str) -> list[WireBody]:
        value = self._body.get(key)
        if value is None or value == "":
            return []
        if not isinstance(value, str):
            raise MappingError(f"{key} should be a JSON string holding an array")
        try:
            parsed = loads_strict(value)
        except BodyError as exc:
            raise MappingError(f"{key} is not a JSON array: {exc}") from exc
        if not isinstance(parsed, list):
            raise MappingError(f"{key} is not a JSON array")
        items: list[WireBody] = []
        for index, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise MappingError(f"{key}[{index}] is not an object")
            try:
                items.append({name: as_scalar(f"{key}[{index}].{name}", element) for name, element in item.items()})
            except BodyError as exc:
                raise MappingError(str(exc)) from exc
        return items
