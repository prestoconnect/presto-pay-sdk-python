from __future__ import annotations

import asyncio
import itertools
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from conftest import MRN, Gateway, async_client, ok, raw_success, sync_client
from presto_pay import (
    PrestoPayApiError,
    PrestoPayConfigError,
    PrestoPayTransportError,
    RetryReads,
)
from presto_pay._core.protocol import QUERY, RawResponse
from presto_pay._core.retry import SendLoop, parse_retry_after, request_not_sent

QUERY_PATH = "/v1/ext/payment/query"
INIT_PATH = "/v1/ext/payment/init"


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://gateway.test/v1/ext/payment/query")


NOT_SENT: list[Exception] = [
    httpx.ConnectError("refused", request=_request()),
    httpx.ConnectTimeout("slow connect", request=_request()),
    httpx.ProxyError("proxy said no", request=_request()),
    httpx.UnsupportedProtocol("ftp?", request=_request()),
    httpx.PoolTimeout("pool exhausted", request=_request()),
]
MAYBE_SENT: list[Exception] = [
    httpx.ReadTimeout("slow read", request=_request()),
    httpx.WriteTimeout("slow write", request=_request()),
    httpx.WriteError("broken pipe", request=_request()),
    httpx.ReadError("reset", request=_request()),
    httpx.RemoteProtocolError("garbage", request=_request()),
    httpx.LocalProtocolError("bad request", request=_request()),
    RuntimeError("an injected client's own failure"),
]


def _name(exc: Exception) -> str:
    return type(exc).__name__


@pytest.mark.parametrize("exc", NOT_SENT, ids=_name)
def test_not_sent_classification(exc: Exception) -> None:
    assert request_not_sent(exc)


@pytest.mark.parametrize("exc", MAYBE_SENT, ids=_name)
def test_everything_else_counts_as_sent(exc: Exception) -> None:
    assert not request_not_sent(exc)


class TestSyncRetryMatrix:
    @pytest.mark.parametrize("exc", NOT_SENT + MAYBE_SENT, ids=_name)
    def test_query_retries_any_transport_failure(self, exc: Exception) -> None:
        gateway = Gateway(exc, ok(raw_success()))
        with sync_client(gateway) as presto:
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert len(gateway.requests) == 2

    @pytest.mark.parametrize("exc", NOT_SENT, ids=_name)
    def test_write_retries_only_when_not_sent(self, exc: Exception) -> None:
        gateway = Gateway(exc, ok(raw_success()))
        with sync_client(gateway) as presto:
            presto.raw.post(INIT_PATH, {"prestoMrn": MRN})
        assert len(gateway.requests) == 2

    @pytest.mark.parametrize("exc", MAYBE_SENT, ids=_name)
    def test_write_never_resends_what_may_have_arrived(self, exc: Exception) -> None:
        gateway = Gateway(exc)
        with sync_client(gateway) as presto, pytest.raises(PrestoPayTransportError) as caught:
            presto.raw.post(INIT_PATH, {"prestoMrn": MRN})
        assert len(gateway.requests) == 1
        assert not caught.value.request_not_sent
        assert caught.value.may_have_taken_effect
        assert caught.value.__cause__ is exc

    def test_query_retries_server_errors(self) -> None:
        gateway = Gateway(httpx.Response(503), httpx.Response(500), ok(raw_success()))
        with sync_client(gateway) as presto:
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert len(gateway.requests) == 3

    def test_query_gives_up_after_max_retries(self) -> None:
        gateway = Gateway(*[httpx.Response(503)] * 3)
        with sync_client(gateway) as presto, pytest.raises(PrestoPayApiError) as caught:
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert caught.value.http_status == 503
        assert len(gateway.requests) == 3

    def test_write_does_not_retry_server_errors(self) -> None:
        gateway = Gateway(httpx.Response(503))
        with sync_client(gateway) as presto, pytest.raises(PrestoPayApiError) as caught:
            presto.raw.post(INIT_PATH, {"prestoMrn": MRN})
        assert caught.value.may_have_taken_effect
        assert len(gateway.requests) == 1

    def test_client_errors_are_not_retried(self) -> None:
        gateway = Gateway(httpx.Response(400))
        with sync_client(gateway) as presto, pytest.raises(PrestoPayApiError):
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert len(gateway.requests) == 1

    def test_redirects_are_neither_followed_nor_retried(self) -> None:
        gateway = Gateway(httpx.Response(307, headers={"location": "https://gateway.test/elsewhere"}))
        with sync_client(gateway) as presto, pytest.raises(PrestoPayApiError, match="HTTP 307"):
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert len(gateway.requests) == 1

    def test_retries_can_be_disabled(self) -> None:
        gateway = Gateway(httpx.Response(503))
        with sync_client(gateway, retry_reads=RetryReads(max_retries=0)) as presto, pytest.raises(PrestoPayApiError):
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert len(gateway.requests) == 1

    def test_every_attempt_is_re_signed_with_a_fresh_ts(self) -> None:
        ticks = itertools.count(1790228276.056, 0.5)
        gateway = Gateway(httpx.Response(503), ok(raw_success()))
        with sync_client(gateway, clock=lambda: next(ticks)) as presto:
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        first, second = gateway.bodies()
        assert first["ts"] != second["ts"]
        assert first["signature"] != second["signature"]

    def test_retry_after_is_honoured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr("presto_pay.client.time.sleep", slept.append)
        gateway = Gateway(httpx.Response(503, headers={"Retry-After": "2"}), ok(raw_success()))
        with sync_client(gateway) as presto:
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert slept == [2.0]

    def test_retry_after_beyond_the_deadline_stops_retrying(self) -> None:
        gateway = Gateway(httpx.Response(503, headers={"Retry-After": "120"}))
        with sync_client(gateway, deadline=5.0) as presto, pytest.raises(PrestoPayApiError):
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert len(gateway.requests) == 1

    def test_each_attempt_gets_the_remaining_deadline_as_its_timeout(self) -> None:
        timeouts: list[dict[str, Any]] = []

        def record(request: httpx.Request) -> httpx.Response:
            timeouts.append(request.extensions["timeout"])
            return ok(raw_success())

        with sync_client(Gateway(record), deadline=7.0) as presto:
            presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert all(0 < value <= 7.0 for value in timeouts[0].values())


class TestAsyncRetryMatrix:
    @pytest.mark.anyio
    async def test_query_retries_then_succeeds(self) -> None:
        gateway = Gateway(NOT_SENT[0], httpx.Response(502), ok(raw_success()))
        async with async_client(gateway) as presto:
            await presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})
        assert len(gateway.requests) == 3

    @pytest.mark.anyio
    async def test_write_never_resends_what_may_have_arrived(self) -> None:
        gateway = Gateway(MAYBE_SENT[0])
        async with async_client(gateway) as presto:
            with pytest.raises(PrestoPayTransportError) as caught:
                await presto.raw.post(INIT_PATH, {"prestoMrn": MRN})
        assert caught.value.may_have_taken_effect
        assert len(gateway.requests) == 1

    @pytest.mark.anyio
    async def test_cancellation_is_never_converted(self) -> None:
        async def hang(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(10)
            raise AssertionError("unreachable")

        http = httpx.AsyncClient(transport=httpx.MockTransport(hang))
        async with async_client(Gateway(), http_client=http) as presto:
            with pytest.raises(TimeoutError):
                async with asyncio.timeout(0.05):
                    await presto.raw.post(QUERY_PATH, {"prestoMrn": MRN})


class TestClientLifecycle:
    def test_injected_client_is_left_open(self) -> None:
        http = httpx.Client(transport=httpx.MockTransport(Gateway()))
        with sync_client(Gateway(), http_client=http):
            pass
        assert not http.is_closed

    def test_sdk_created_client_is_closed(self) -> None:
        presto = sync_client(Gateway(), http_client=None)
        with presto:
            pass
        assert presto._http.is_closed

    @pytest.mark.anyio
    async def test_async_injected_client_is_left_open(self) -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(Gateway()))
        async with async_client(Gateway(), http_client=http):
            pass
        assert not http.is_closed
        await http.aclose()


class TestSendLoop:
    def _loop(self, *, now: list[float], rng: float = 1.0, policy: RetryReads | None = None) -> SendLoop:
        return SendLoop(
            write=False,
            policy=policy or RetryReads(max_retries=5, initial_backoff=0.2, max_backoff=1.0),
            deadline=30.0,
            monotonic=lambda: now[0],
            wall_clock=lambda: 1_000_000.0,
            rng=lambda: rng,
        )

    def test_exponential_backoff_is_capped(self) -> None:
        loop = self._loop(now=[0.0])
        delays = [loop.delay_after_response(RawResponse(503, {}, b"")) for _ in range(5)]
        assert delays == [0.2, 0.4, 0.8, 1.0, 1.0]

    def test_full_jitter_scales_the_ceiling(self) -> None:
        loop = self._loop(now=[0.0], rng=0.25)
        assert loop.delay_after_response(RawResponse(503, {}, b"")) == pytest.approx(0.05)

    def test_jitter_can_be_turned_off(self) -> None:
        loop = self._loop(now=[0.0], rng=0.0, policy=RetryReads(initial_backoff=0.3, max_backoff=1.0, jitter=False))
        assert loop.delay_after_response(RawResponse(503, {}, b"")) == 0.3

    def test_deadline_counts_down(self) -> None:
        now = [0.0]
        loop = self._loop(now=now)
        now[0] = 29.9
        assert loop.remaining() == pytest.approx(0.1)
        assert loop.delay_after_response(RawResponse(503, {}, b"")) is None

    def test_writes_ignore_server_errors(self) -> None:
        loop = SendLoop(write=True, policy=RetryReads(), deadline=30.0)
        assert loop.delay_after_response(RawResponse(503, {}, b"")) is None
        assert loop.delay_after_transport_error(NOT_SENT[0]) is not None

    def test_query_ignores_non_server_errors(self) -> None:
        loop = SendLoop(write=False, policy=RetryReads(), deadline=30.0)
        assert loop.delay_after_response(RawResponse(404, {}, b"")) is None
        assert loop.delay_after_response(RawResponse(200, {}, b"")) is None


class TestRetryAfter:
    def test_seconds(self) -> None:
        assert parse_retry_after("3", 0.0) == 3.0

    def test_http_date(self) -> None:
        now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
        header = format_datetime(datetime(2026, 9, 30, 12, 0, 5, tzinfo=UTC), usegmt=True)
        assert parse_retry_after(header, now.timestamp()) == pytest.approx(5.0)

    @pytest.mark.parametrize("value", [None, "", "soon", "-1"])
    def test_unusable(self, value: str | None) -> None:
        assert parse_retry_after(value, 0.0) is None


@pytest.mark.parametrize(
    "options",
    [
        {"max_retries": -1},
        {"max_retries": True},
        {"initial_backoff": 2.0, "max_backoff": 1.0},
        {"initial_backoff": -0.1},
    ],
)
def test_invalid_retry_policy(options: dict[str, Any]) -> None:
    with pytest.raises(PrestoPayConfigError):
        RetryReads(**options)


def test_query_operation_is_the_only_read() -> None:
    assert not QUERY.write
