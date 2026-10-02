from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from presto_pay._core.canonical import BodyError, canonical_string, parse_body
from presto_pay._core.crypto import verify
from presto_pay._core.keys import PublicKeyInput, coerce_public_keys
from presto_pay._core.mapping import FieldReader, MappingError
from presto_pay._core.redaction import describe_body, describe_canonical
from presto_pay._core.timestamp import format_epoch_seconds, parse_gateway_timestamp, to_epoch_seconds
from presto_pay.errors import PrestoPayConfigError, PrestoPayResponseError, PrestoPaySignatureError
from presto_pay.webhooks.events import WebhookEvent, map_event

DEFAULT_MAX_TIMESTAMP_AGE = 15 * 60.0

RAW_BODY_HINT = (
    "pass the raw request body: request.body (Django, Pyramid), request.get_data() (Flask), "
    "await request.body() (FastAPI, Starlette) or await request.read() (aiohttp); a parsed and re-serialized "
    "dict no longer matches the bytes Presto signed"
)


@dataclass(frozen=True, slots=True)
class WebhookOptions:
    max_timestamp_age: float | None = DEFAULT_MAX_TIMESTAMP_AGE

    def __post_init__(self) -> None:
        _check_max_age(self.max_timestamp_age)


class WebhookVerifier:
    def __init__(
        self,
        *,
        merchant_ids: str | Iterable[str],
        presto_public_keys: PublicKeyInput | Sequence[PublicKeyInput],
        max_timestamp_age: float | None = DEFAULT_MAX_TIMESTAMP_AGE,
        strict: bool = False,
        redact_error_bodies: bool = True,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._merchant_ids = merchant_id_set(merchant_ids)
        self._keys = coerce_public_keys(presto_public_keys)
        self._max_age = _check_max_age(max_timestamp_age)
        self._strict = strict
        self._redact = redact_error_bodies
        self._clock = clock

    @property
    def merchant_ids(self) -> frozenset[str]:
        return self._merchant_ids

    def verify(self, body: bytes | bytearray | memoryview | str) -> WebhookEvent:
        raw = _raw_bytes(body)
        try:
            parsed = parse_body(raw)
        except BodyError as exc:
            raise self._malformed(f"Webhook body is malformed: {exc}", raw) from exc

        signature = parsed.get("signature")
        if not verify(self._keys, canonical_string(parsed), signature):
            reason = (
                "carries no signature"
                if not isinstance(signature, str) or not signature
                else "does not verify against any configured Presto public key"
            )
            raise PrestoPaySignatureError(
                f"Webhook {reason}",
                operation="webhook",
                source="webhook",
                canonical=describe_canonical(parsed, redact=self._redact),
            )

        try:
            event = map_event(FieldReader(parsed, strict=self._strict))
            sent_at = parse_gateway_timestamp(event.ts)
        except (MappingError, ValueError) as exc:
            raise self._malformed(f"Webhook body is malformed: {exc}", raw) from exc

        if event.mid not in self._merchant_ids:
            # One Presto key signs for every merchant, so a valid signature does not make the event ours.
            raise PrestoPaySignatureError(
                f"Webhook is for merchant {event.mid!r}, which is not a configured merchant ID",
                operation="webhook",
                source="webhook",
            )

        if self._max_age is not None:
            now = self._clock()
            age = now - to_epoch_seconds(sent_at)
            if abs(age) > self._max_age:
                raise PrestoPaySignatureError(
                    f"Webhook ts {event.ts} is {age:+.0f}s from this host's clock ({format_epoch_seconds(now)}), "
                    f"outside the {self._max_age:.0f}s window. Check the host clock; widen max_timestamp_age "
                    "only if your order update finalises an order only once",
                    operation="webhook",
                    source="webhook",
                )
        return event

    def _malformed(self, message: str, raw: bytes) -> PrestoPayResponseError:
        return PrestoPayResponseError(
            message,
            operation="webhook",
            source="webhook",
            raw_body=describe_body(raw, None, redact=self._redact),
        )


def create_webhook_verifier(
    *,
    merchant_id: str | Iterable[str],
    presto_public_key: PublicKeyInput | Sequence[PublicKeyInput],
    max_timestamp_age: float | None = DEFAULT_MAX_TIMESTAMP_AGE,
    strict: bool = False,
    redact_error_bodies: bool = True,
    clock: Callable[[], float] = time.time,
) -> WebhookVerifier:
    return WebhookVerifier(
        merchant_ids=merchant_id,
        presto_public_keys=presto_public_key,
        max_timestamp_age=max_timestamp_age,
        strict=strict,
        redact_error_bodies=redact_error_bodies,
        clock=clock,
    )


def merchant_id_set(merchant_id: str | Iterable[str]) -> frozenset[str]:
    ids = frozenset([merchant_id] if isinstance(merchant_id, str) else merchant_id)
    if not ids or not all(isinstance(mid, str) and mid for mid in ids):
        raise PrestoPayConfigError("merchant_id needs at least one non-empty merchant ID", field="merchant_id")
    return ids


def _raw_bytes(body: object) -> bytes:
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray | memoryview):
        return bytes(body)
    if isinstance(body, str):
        return body.encode("utf-8", errors="surrogatepass")
    raise PrestoPayConfigError(
        f"webhooks.verify got {type(body).__name__}; {RAW_BODY_HINT}", field="body", operation="webhook"
    )


def _check_max_age(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        raise PrestoPayConfigError(
            "max_timestamp_age must be a positive, finite number of seconds, or None to disable the check",
            field="max_timestamp_age",
        )
    return float(value)
