from __future__ import annotations

import asyncio
import functools
import ipaddress
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import ClassVar, Concatenate, Generic, Literal, ParamSpec, Self, TypeVar
from urllib.parse import urlsplit

import httpx

from presto_pay._core.canonical import BodyError, JsonScalar, WireBody, canonical_string, parse_body
from presto_pay._core.crypto import sign, verify
from presto_pay._core.keys import (
    Password,
    PrestoPublicKey,
    PrivateKeyInput,
    PublicKeyInput,
    coerce_private_key,
    coerce_public_keys,
)
from presto_pay._core.mapping import FieldReader
from presto_pay._core.protocol import (
    QUERY,
    USER_AGENT,
    OperationSpec,
    PreparedRequest,
    ProtocolConfig,
    RawResponse,
    interpret,
    prepare,
)
from presto_pay._core.redaction import describe_body, describe_canonical
from presto_pay._core.retry import RetryReads, SendLoop
from presto_pay.errors import PrestoPayConfigError, PrestoPayResponseError, PrestoPaySignatureError, ReconcileKey
from presto_pay.payments import to_wire
from presto_pay.payments.inputs import check_documented_lengths
from presto_pay.payments.to_wire import Call

T = TypeVar("T")
P = ParamSpec("P")
HttpClientT = TypeVar("HttpClientT", httpx.Client, httpx.AsyncClient)

_RAW_PATH = re.compile(r"/v1/ext/[A-Za-z0-9/_-]+")


def _validated_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise PrestoPayConfigError("environment base_url must be a string", field="environment")
    parts = urlsplit(value)
    if not parts.hostname or parts.query or parts.fragment:
        raise PrestoPayConfigError(f"{value!r} is not a gateway base URL", field="environment")
    if parts.scheme != "https" and not (parts.scheme == "http" and _is_loopback(parts.hostname)):
        raise PrestoPayConfigError(
            f"{value!r} must use https (plain http is allowed only for a loopback test gateway)", field="environment"
        )
    return value.rstrip("/")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class Environment:
    base_url: str

    STAGING: ClassVar[Environment]
    PRODUCTION: ClassVar[Environment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _validated_base_url(self.base_url))


Environment.STAGING = Environment("https://presto-stg-ext.enovax.com")
Environment.PRODUCTION = Environment("https://pay-ext.prestouniverse.com")

EnvironmentInput = Literal["staging", "production"] | Environment


def _resolve_environment(environment: EnvironmentInput) -> Environment:
    if isinstance(environment, Environment):
        return environment
    if environment == "staging":
        return Environment.STAGING
    if environment == "production":
        return Environment.PRODUCTION
    raise PrestoPayConfigError(
        f"environment must be 'staging', 'production' or an Environment, not {environment!r}", field="environment"
    )


def _raw_operation(path: str) -> OperationSpec:
    if not isinstance(path, str) or _RAW_PATH.fullmatch(path) is None:
        raise PrestoPayConfigError(f"{path!r} is not a gateway path under /v1/ext/", field="path")
    if path == QUERY.path:
        return OperationSpec("raw", path, write=False)
    return OperationSpec("raw", path, write=True)


def _raw_response(response: httpx.Response) -> RawResponse:
    return RawResponse(status=response.status_code, headers=dict(response.headers.items()), body=response.content)


def _whole_body(reader: FieldReader) -> WireBody:
    return dict(reader.body)


class _BaseClient(Generic[HttpClientT]):
    def __init__(
        self,
        *,
        environment: EnvironmentInput,
        merchant_id: str,
        private_key: PrivateKeyInput,
        presto_public_key: PublicKeyInput | Sequence[PublicKeyInput],
        private_key_password: Password = None,
        deadline: float = 30.0,
        retry_reads: RetryReads | None = None,
        strict: bool = False,
        redact_error_bodies: bool = True,
        http_client: HttpClientT | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(merchant_id, str) or not merchant_id:
            raise PrestoPayConfigError("merchant_id must be a non-empty string", field="merchant_id")
        if isinstance(deadline, bool) or not isinstance(deadline, int | float) or deadline <= 0:
            raise PrestoPayConfigError("deadline must be a positive number of seconds", field="deadline")
        self._protocol = ProtocolConfig(
            base_url=_resolve_environment(environment).base_url,
            merchant_id=merchant_id,
            private_key=coerce_private_key(private_key, private_key_password),
            presto_public_keys=coerce_public_keys(presto_public_key),
            strict=strict,
            redact_error_bodies=redact_error_bodies,
        )
        self._deadline = float(deadline)
        self._retry_reads = retry_reads if retry_reads is not None else RetryReads()
        self._clock = clock
        self._owns_http_client = http_client is None
        self._http: HttpClientT = http_client if http_client is not None else self._new_http_client()
        self._attach_namespaces()

    def _new_http_client(self) -> HttpClientT:
        raise NotImplementedError

    def _attach_namespaces(self) -> None:
        raise NotImplementedError

    @property
    def merchant_id(self) -> str:
        return self._protocol.merchant_id

    @property
    def base_url(self) -> str:
        return self._protocol.base_url

    @property
    def presto_public_keys(self) -> tuple[PrestoPublicKey, ...]:
        return self._protocol.presto_public_keys

    def _prepare(
        self, operation: OperationSpec, fields: Mapping[str, JsonScalar], reconcile_by: ReconcileKey | None
    ) -> PreparedRequest:
        return prepare(operation, fields, self._protocol, self._clock(), reconcile_by)

    def _checked(self, call: Call[T]) -> Call[T]:
        if self._protocol.strict:
            check_documented_lengths(call.fields, call.documented_lengths, call.operation.name)
        return call

    def _send_loop(self, operation: OperationSpec) -> SendLoop:
        return SendLoop(write=operation.write, policy=self._retry_reads, deadline=self._deadline)

    def _sign(self, canonical: str) -> str:
        return sign(self._protocol.private_key, canonical)

    def _verify_body(self, body: bytes | str) -> WireBody:
        raw = body.encode("utf-8") if isinstance(body, str) else body
        redact = self._protocol.redact_error_bodies
        try:
            parsed = parse_body(raw)
        except BodyError as exc:
            raise PrestoPayResponseError(
                f"Body is malformed: {exc}",
                operation="raw",
                source="response",
                raw_body=describe_body(raw, None, redact=redact),
            ) from exc
        if not verify(self._protocol.presto_public_keys, canonical_string(parsed), parsed.get("signature")):
            raise PrestoPaySignatureError(
                "Body signature does not verify against any configured Presto public key",
                operation="raw",
                source="response",
                canonical=describe_canonical(parsed, redact=redact),
            )
        return parsed

    def __repr__(self) -> str:
        return f"{type(self).__name__}(merchant_id={self.merchant_id!r}, base_url={self.base_url!r})"


class PrestoPay(_BaseClient[httpx.Client]):
    payments: Payments
    raw: Raw

    def _attach_namespaces(self) -> None:
        self.payments = Payments(self)
        self.raw = Raw(self)

    def _new_http_client(self) -> httpx.Client:
        return httpx.Client(follow_redirects=False, headers={"User-Agent": USER_AGENT})

    def _execute(
        self,
        operation: OperationSpec,
        fields: Mapping[str, JsonScalar],
        reconcile_by: ReconcileKey | None,
        mapper: Callable[[FieldReader], T],
    ) -> T:
        loop = self._send_loop(operation)
        while True:
            prepared = self._prepare(operation, fields, reconcile_by)
            try:
                response = _raw_response(
                    self._http.post(
                        prepared.url,
                        content=prepared.body,
                        headers=prepared.headers,
                        timeout=loop.timeout(),
                        follow_redirects=False,
                    )
                )
            except Exception as exc:
                delay = loop.delay_after_transport_error(exc)
                if delay is None:
                    raise loop.transport_error(prepared, exc) from exc
                time.sleep(delay)
                continue
            delay = loop.delay_after_response(response)
            if delay is None:
                return interpret(prepared, response, self._protocol, mapper)
            time.sleep(delay)

    def _run(self, call: Call[T]) -> T:
        call = self._checked(call)
        return self._execute(call.operation, call.fields, call.reconcile_by, call.mapper)

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.close()


class AsyncPrestoPay(_BaseClient[httpx.AsyncClient]):
    payments: AsyncPayments
    raw: AsyncRaw

    def _attach_namespaces(self) -> None:
        self.payments = AsyncPayments(self)
        self.raw = AsyncRaw(self)

    def _new_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(follow_redirects=False, headers={"User-Agent": USER_AGENT})

    async def _execute(
        self,
        operation: OperationSpec,
        fields: Mapping[str, JsonScalar],
        reconcile_by: ReconcileKey | None,
        mapper: Callable[[FieldReader], T],
    ) -> T:
        loop = self._send_loop(operation)
        while True:
            prepared = self._prepare(operation, fields, reconcile_by)
            try:
                response = _raw_response(
                    await self._http.post(
                        prepared.url,
                        content=prepared.body,
                        headers=prepared.headers,
                        timeout=loop.timeout(),
                        follow_redirects=False,
                    )
                )
            except Exception as exc:
                delay = loop.delay_after_transport_error(exc)
                if delay is None:
                    raise loop.transport_error(prepared, exc) from exc
                await asyncio.sleep(delay)
                continue
            delay = loop.delay_after_response(response)
            if delay is None:
                return interpret(prepared, response, self._protocol, mapper)
            await asyncio.sleep(delay)

    async def _run(self, call: Call[T]) -> T:
        call = self._checked(call)
        return await self._execute(call.operation, call.fields, call.reconcile_by, call.mapper)

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        await self.aclose()


def _sync_operation(build: Callable[P, Call[T]]) -> Callable[Concatenate[Payments, P], T]:
    @functools.wraps(build)
    def operation(self: Payments, /, *args: P.args, **kwargs: P.kwargs) -> T:
        return self._client._run(build(*args, **kwargs))

    return operation


def _async_operation(build: Callable[P, Call[T]]) -> Callable[Concatenate[AsyncPayments, P], Awaitable[T]]:
    @functools.wraps(build)
    async def operation(self: AsyncPayments, /, *args: P.args, **kwargs: P.kwargs) -> T:
        return await self._client._run(build(*args, **kwargs))

    return operation


class Payments:
    def __init__(self, client: PrestoPay) -> None:
        self._client = client

    init = _sync_operation(to_wire.init)
    query = _sync_operation(to_wire.query)
    reverse = _sync_operation(to_wire.reverse)
    refund = _sync_operation(to_wire.refund)


class AsyncPayments:
    def __init__(self, client: AsyncPrestoPay) -> None:
        self._client = client

    init = _async_operation(to_wire.init)
    query = _async_operation(to_wire.query)
    reverse = _async_operation(to_wire.reverse)
    refund = _async_operation(to_wire.refund)


class Raw:
    def __init__(self, client: PrestoPay) -> None:
        self._client = client

    def post(self, path: str, body: Mapping[str, JsonScalar]) -> WireBody:
        return self._client._execute(_raw_operation(path), body, None, _whole_body)

    def sign(self, canonical: str) -> str:
        return self._client._sign(canonical)

    def verify_body(self, body: bytes | str) -> WireBody:
        return self._client._verify_body(body)


class AsyncRaw:
    def __init__(self, client: AsyncPrestoPay) -> None:
        self._client = client

    async def post(self, path: str, body: Mapping[str, JsonScalar]) -> WireBody:
        return await self._client._execute(_raw_operation(path), body, None, _whole_body)

    def sign(self, canonical: str) -> str:
        return self._client._sign(canonical)

    def verify_body(self, body: bytes | str) -> WireBody:
        return self._client._verify_body(body)
