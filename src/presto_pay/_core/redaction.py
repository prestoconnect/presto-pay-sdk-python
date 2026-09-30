from __future__ import annotations

import json
from collections.abc import Mapping

from presto_pay._core.canonical import BodyError, JsonScalar, WireBody, canonical_string, dumps_compact, parse_body

PERSONAL_FIELDS = frozenset({"cardBin", "cardSummary", "receiptEmail", "receiptName"})
STRINGIFIED_LIST_FIELDS = frozenset({"itemList", "paymentDetails", "refundDetails"})
REDACTED = "[redacted]"


def redact_body(body: Mapping[str, JsonScalar]) -> WireBody:
    return {key: _redact_field(key, value) for key, value in body.items()}


def describe_body(raw: bytes, body: Mapping[str, JsonScalar] | None, *, redact: bool) -> str:
    if not redact:
        return raw.decode("utf-8", errors="replace")
    if body is None:
        try:
            body = parse_body(raw)
        except BodyError:
            return f"{REDACTED} {len(raw)} bytes that are not a JSON object"
    return dumps_compact(redact_body(body))


def describe_canonical(body: Mapping[str, JsonScalar], *, redact: bool) -> str:
    return canonical_string(redact_body(body) if redact else body)


def _redact_field(key: str, value: JsonScalar) -> JsonScalar:
    if value is None or value == "":
        return value
    if key in PERSONAL_FIELDS:
        return REDACTED
    if key in STRINGIFIED_LIST_FIELDS and isinstance(value, str):
        return _redact_stringified_list(value)
    return value


def _redact_stringified_list(text: str) -> str:
    try:
        items = json.loads(text)
    except ValueError:
        return REDACTED
    if not isinstance(items, list):
        return REDACTED
    redacted = [
        {
            name: REDACTED if name in PERSONAL_FIELDS and element not in (None, "") else element
            for name, element in item.items()
        }
        if isinstance(item, dict)
        else item
        for item in items
    ]
    return dumps_compact(redacted)
