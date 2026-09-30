from __future__ import annotations

import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import httpx

from presto_pay._core.protocol import PreparedRequest, RawResponse
from presto_pay.errors import PrestoPayConfigError, PrestoPayTransportError

# None of these can have written a request byte: they fail while resolving, connecting, negotiating TLS
# (httpx reports TLS failures as ConnectError) or waiting for a pooled connection. Everything else, including
# exception types an injected client invents, is treated as possibly sent.
NOT_SENT_ERRORS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ProxyError,
    httpx.UnsupportedProtocol,
    httpx.PoolTimeout,
)


@dataclass(frozen=True, slots=True)
class RetryReads:
    max_retries: int = 2
    initial_backoff: float = 0.2
    max_backoff: float = 5.0
    jitter: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise PrestoPayConfigError("retry_reads.max_retries must be an int >= 0", field="retry_reads")
        if not (math.isfinite(self.initial_backoff) and math.isfinite(self.max_backoff)) or not (
            0 <= self.initial_backoff <= self.max_backoff
        ):
            raise PrestoPayConfigError("retry_reads needs 0 <= initial_backoff <= max_backoff", field="retry_reads")


def request_not_sent(exc: BaseException) -> bool:
    return isinstance(exc, NOT_SENT_ERRORS)


def parse_retry_after(value: str | None, now: float) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return float(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, moment.timestamp() - now)


class DeadlineExceeded(Exception):
    pass


class SendLoop:
    def __init__(
        self,
        *,
        write: bool,
        policy: RetryReads,
        deadline: float,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._write = write
        self._policy = policy
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._rng = rng
        self._deadline = deadline
        self._deadline_at = monotonic() + deadline
        self._attempt = 0

    def remaining(self) -> float:
        return max(0.0, self._deadline_at - self._monotonic())

    def timeout(self) -> httpx.Timeout:
        return httpx.Timeout(max(self.remaining(), 0.001))

    def deadline_exceeded(self) -> DeadlineExceeded:
        return DeadlineExceeded(f"the {self._deadline:g}s deadline for the whole call ran out")

    def check_deadline(self) -> None:
        if self.remaining() <= 0:
            raise self.deadline_exceeded()

    def delay_after_transport_error(self, exc: BaseException) -> float | None:
        if self._write and not request_not_sent(exc):
            return None
        return self._next_delay(None)

    def delay_after_response(self, response: RawResponse) -> float | None:
        if self._write or response.status < 500:
            return None
        return self._next_delay(response.header("retry-after"))

    def transport_error(self, prepared: PreparedRequest, exc: BaseException) -> PrestoPayTransportError:
        not_sent = request_not_sent(exc)
        operation = prepared.operation
        consequence = (
            "the request was not sent"
            if not_sent
            else "the request may have reached the gateway"
            if operation.write
            else "no payment state changed"
        )
        return PrestoPayTransportError(
            f"Could not complete {operation.name} with the gateway ({type(exc).__name__}: {exc}); {consequence}",
            operation=operation.name,
            request_not_sent=not_sent,
            may_have_taken_effect=operation.write and not not_sent,
            reconcile_by=prepared.reconcile_by,
        )

    def _next_delay(self, retry_after: str | None) -> float | None:
        if self._attempt >= self._policy.max_retries:
            return None
        requested = parse_retry_after(retry_after, self._wall_clock())
        if requested is None:
            ceiling = min(self._policy.initial_backoff * 2**self._attempt, self._policy.max_backoff)
            requested = ceiling * self._rng() if self._policy.jitter else ceiling
        remaining = self.remaining()
        if requested >= remaining:
            return None
        self._attempt += 1
        return requested
