from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeVar

from presto_pay._core.canonical import BodyError, JsonScalar, WireBody, canonical_string, dumps_compact, parse_body
from presto_pay._core.crypto import sign, verify
from presto_pay._core.keys import PrestoPublicKey, PrivateKey
from presto_pay._core.mapping import FieldReader, MappingError, to_snake
from presto_pay._core.redaction import describe_body, describe_canonical
from presto_pay._core.timestamp import format_epoch_seconds, parse_gateway_timestamp
from presto_pay._version import __version__
from presto_pay.constants import ErrorCode
from presto_pay.errors import (
    PrestoPayApiError,
    PrestoPayConfigError,
    PrestoPayResponseError,
    PrestoPaySignatureError,
    ReconcileKey,
)

T = TypeVar("T")

OperationName = Literal["init", "query", "reverse", "refund", "raw"]

USER_AGENT = f"presto-pay-sdk-python/{__version__}"
CONTENT_TYPE = "application/json; charset=UTF-8"
REQUEST_VALIDITY_SECONDS = 15 * 60
SDK_OWNED_FIELDS = ("mid", "ts", "signature")


@dataclass(frozen=True, slots=True)
class OperationSpec:
    name: OperationName
    path: str
    write: bool


INIT = OperationSpec("init", "/v1/ext/payment/init", write=True)
QUERY = OperationSpec("query", "/v1/ext/payment/query", write=False)
REVERSE = OperationSpec("reverse", "/v1/ext/payment/reverse", write=True)
REFUND = OperationSpec("refund", "/v1/ext/payment/refund", write=True)


@dataclass(frozen=True, slots=True)
class ProtocolConfig:
    base_url: str
    merchant_id: str
    private_key: PrivateKey
    presto_public_keys: tuple[PrestoPublicKey, ...]
    strict: bool = False
    redact_error_bodies: bool = True


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    operation: OperationSpec
    url: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    signed_body: WireBody = field(repr=False)
    canonical: str = field(repr=False)
    ts: str
    reconcile_by: ReconcileKey | None
    method: str = "POST"


@dataclass(frozen=True, slots=True)
class RawResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return None


def prepare(
    operation: OperationSpec,
    fields: Mapping[str, JsonScalar],
    config: ProtocolConfig,
    now: float,
    reconcile_by: ReconcileKey | None = None,
) -> PreparedRequest:
    for reserved in SDK_OWNED_FIELDS:
        if reserved in fields:
            raise PrestoPayConfigError(f"{reserved} is set by the SDK and must not be passed in", field=reserved)
    for key, value in fields.items():
        if isinstance(value, str):
            _require_utf8(key, value, operation.name)
    ts = format_epoch_seconds(now)
    body: WireBody = {**fields, "mid": config.merchant_id, "ts": ts}
    try:
        canonical = canonical_string(body)
    except BodyError as exc:
        raise PrestoPayConfigError(f"request body cannot be signed: {exc}", operation=operation.name) from exc
    body["signature"] = sign(config.private_key, canonical)
    return PreparedRequest(
        operation=operation,
        url=config.base_url + operation.path,
        headers=(("Content-Type", CONTENT_TYPE), ("User-Agent", USER_AGENT), ("Accept", "application/json")),
        body=dumps_compact(body).encode("utf-8"),
        signed_body=body,
        canonical=canonical,
        ts=ts,
        reconcile_by=reconcile_by,
    )


def interpret(
    prepared: PreparedRequest,
    response: RawResponse,
    config: ProtocolConfig,
    mapper: Callable[[FieldReader], T],
) -> T:
    operation = prepared.operation
    redact = config.redact_error_bodies
    if response.status != 200:
        raise _http_error(prepared, response, redact)

    def response_error(message: str, body: WireBody | None) -> PrestoPayResponseError:
        return PrestoPayResponseError(
            message,
            operation=operation.name,
            source="response",
            raw_body=describe_body(response.body, body, redact=redact),
            may_have_taken_effect=operation.write,
            reconcile_by=prepared.reconcile_by,
        )

    try:
        body = parse_body(response.body)
    except BodyError as exc:
        raise response_error(f"Gateway response to {operation.name} is malformed: {exc}", None) from exc

    signature = body.get("signature")
    if not verify(config.presto_public_keys, canonical_string(body), signature):
        reason = (
            "carries no signature"
            if not isinstance(signature, str) or not signature
            else "does not verify against any configured Presto public key"
        )
        raise PrestoPaySignatureError(
            f"Gateway response to {operation.name} {reason}",
            operation=operation.name,
            source="response",
            canonical=describe_canonical(body, redact=redact),
            may_have_taken_effect=operation.write,
            reconcile_by=prepared.reconcile_by,
        )

    success = body.get("success")
    if not isinstance(success, bool):
        raise response_error(f"Gateway response to {operation.name} has no boolean success field", body)
    if not success:
        raise _business_error(prepared, response, body, config)

    reader = FieldReader(body, strict=config.strict)
    try:
        _require_gateway_timestamp(reader)
        result = mapper(reader)
    except MappingError as exc:
        raise response_error(f"Gateway response to {operation.name} is malformed: {exc}", body) from exc

    mismatch = _echo_mismatch(prepared.signed_body, body)
    if mismatch is not None:
        raise response_error(f"Gateway response to {operation.name} answers a different request: {mismatch}", body)
    return result


def _require_utf8(key: str, value: str, operation: OperationName) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PrestoPayConfigError(
            f"{to_snake(key)} contains characters that cannot be sent as UTF-8 (an unpaired surrogate)",
            field=to_snake(key),
            operation=operation,
        ) from exc


def _require_gateway_timestamp(reader: FieldReader) -> None:
    ts = reader.required_str("ts")
    try:
        parse_gateway_timestamp(ts)
    except ValueError as exc:
        raise MappingError(str(exc)) from exc


def _echo_mismatch(sent: Mapping[str, JsonScalar], received: Mapping[str, JsonScalar]) -> str | None:
    sent_mrn = sent.get("prestoMrn")
    if sent_mrn is not None and received.get("prestoMrn") != sent_mrn:
        return f"prestoMrn {received.get('prestoMrn')!r} was sent as {sent_mrn!r}"
    sent_txn = sent.get("txnRefNum")
    received_txn = received.get("txnRefNum")
    if sent_txn is not None and received_txn not in (None, "") and received_txn != sent_txn:
        return f"txnRefNum {received_txn!r} was sent as {sent_txn!r}"
    return None


def _http_error(prepared: PreparedRequest, response: RawResponse, redact: bool) -> PrestoPayApiError:
    operation = prepared.operation
    code = response.header("x-http-error-code") or None
    detail = response.header("x-http-error") or None
    described = " ".join(part for part in (code, detail) if part)
    message = f"Gateway returned HTTP {response.status} for {operation.name}" + (f": {described}" if described else "")
    return PrestoPayApiError(
        message,
        operation=operation.name,
        kind="http",
        http_status=response.status,
        error_code=code,
        error_message=detail,
        raw_body=describe_body(response.body, None, redact=redact) if response.body else None,
        may_have_taken_effect=operation.write and response.status >= 500,
        reconcile_by=prepared.reconcile_by,
    )


def _business_error(
    prepared: PreparedRequest, response: RawResponse, body: WireBody, config: ProtocolConfig
) -> PrestoPayApiError:
    operation = prepared.operation
    reader = FieldReader(body, strict=False)
    code = reader.optional_str("errorCode")
    detail = reader.optional_str("errorMessage")
    message = f"Gateway rejected {operation.name}" + (f" ({code})" if code else "") + (f": {detail}" if detail else "")
    canonical: str | None = None
    clock_offset: float | None = None
    may_have_taken_effect = False

    if code in (ErrorCode.INVALID_SIGNATURE, ErrorCode.SIGNATURE_VERIFICATION_FAILED):
        canonical = describe_canonical(prepared.signed_body, redact=config.redact_error_bodies)
        message = (
            f"Gateway could not verify the request signature ({code}); check that the private key matches the "
            "certificate registered with Presto, and compare `canonical` with the string the gateway signed"
        )
    elif code == ErrorCode.CLOCK_SKEW:
        clock_offset = _clock_offset(prepared.ts, reader.optional_str("ts"))
        observed = (
            f"; the gateway clock reads {clock_offset:+.1f}s from this host's" if clock_offset is not None else ""
        )
        message = (
            f"Gateway rejected the request timestamp ({code}): it must be within "
            f"{REQUEST_VALIDITY_SECONDS // 60} minutes of the gateway clock{observed}. Check the host clock (NTP)"
        )
    elif code == ErrorCode.DUPLICATE_TXN_REF_NUM and operation.name == "init":
        # 1203 proves a payment record exists for this txnRefNum but not what state it is in, so the caller must
        # query rather than treat it as either a success or a clean failure.
        may_have_taken_effect = True

    return PrestoPayApiError(
        message,
        operation=operation.name,
        kind="business",
        http_status=200,
        error_code=code,
        error_message=detail,
        raw_body=describe_body(response.body, body, redact=config.redact_error_bodies),
        may_have_taken_effect=may_have_taken_effect,
        reconcile_by=prepared.reconcile_by,
        canonical=canonical,
        clock_offset=clock_offset,
    )


def _clock_offset(sent_ts: str, received_ts: str | None) -> float | None:
    if received_ts is None:
        return None
    try:
        return (parse_gateway_timestamp(received_ts) - parse_gateway_timestamp(sent_ts)).total_seconds()
    except ValueError:
        return None
