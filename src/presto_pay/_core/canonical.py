from __future__ import annotations

import json
from collections.abc import Mapping
from typing import NoReturn

JsonScalar = str | int | bool | None
WireBody = dict[str, JsonScalar]

MAX_SAFE_INTEGER = 2**53 - 1


class BodyError(ValueError):
    pass


def _reject_float(token: str) -> NoReturn:
    raise BodyError(f"non-integer number {token}")


def _reject_constant(token: str) -> NoReturn:
    raise BodyError(f"not valid JSON: {token}")


def loads_strict(text: str) -> object:
    try:
        return json.loads(text, parse_float=_reject_float, parse_constant=_reject_constant)
    except BodyError:
        raise
    except ValueError as exc:
        raise BodyError(f"not valid JSON: {exc}") from exc


def parse_body(data: bytes | str) -> WireBody:
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    parsed = loads_strict(text)
    if not isinstance(parsed, dict):
        raise BodyError("not a JSON object")
    return {key: as_scalar(key, value) for key, value in parsed.items()}


def as_scalar(key: str, value: object) -> JsonScalar:
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise BodyError(f"{key}: integer outside +-(2^53 - 1)")
        return value
    if isinstance(value, list):
        raise BodyError(f"{key}: array value")
    if isinstance(value, dict):
        raise BodyError(f"{key}: object value")
    raise BodyError(f"{key}: unsupported value of type {type(value).__name__}")


def render_value(value: JsonScalar) -> str:
    if value is None:
        return ""
    # bool is a subclass of int, so it must be matched first or True renders as "1".
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return value


def canonical_string(body: Mapping[str, object]) -> str:
    return ":".join(render_value(as_scalar(key, body[key])) for key in sorted(body) if key != "signature")


def canonicalize(body: bytes | str) -> str:
    return canonical_string(parse_body(body))


def dumps_compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
