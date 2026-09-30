from __future__ import annotations

import datetime
import ipaddress
import socket
import ssl
import struct
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from conftest import MID, MRN, TEST_CERT_PEM, TEST_PRIVATE_KEY
from presto_pay import Environment, PrestoPay, PrestoPayTransportError, RetryReads

pytestmark = pytest.mark.sockets

INIT_PATH = "/v1/ext/payment/init"


def _client(base_url: str, deadline: float = 5.0) -> PrestoPay:
    return PrestoPay(
        environment=Environment(base_url),
        merchant_id=MID,
        private_key=TEST_PRIVATE_KEY,
        presto_public_key=TEST_CERT_PEM,
        deadline=deadline,
        retry_reads=RetryReads(max_retries=0),
    )


def _init_failure(base_url: str, deadline: float = 5.0) -> PrestoPayTransportError:
    with _client(base_url, deadline) as presto, pytest.raises(PrestoPayTransportError) as caught:
        presto.raw.post(INIT_PATH, {"prestoMrn": MRN})
    return caught.value


def _read_request(connection: socket.socket) -> bytes:
    received = b""
    while b"\r\n\r\n" not in received:
        chunk = connection.recv(65536)
        if not chunk:
            return received
        received += chunk
    head, _, body = received.partition(b"\r\n\r\n")
    length = next(
        int(line.split(b":", 1)[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length:")
    )
    while len(body) < length:
        chunk = connection.recv(65536)
        if not chunk:
            break
        body += chunk
    return head + b"\r\n\r\n" + body


@contextmanager
def _server(handle: Callable[[socket.socket], None], wrap: ssl.SSLContext | None = None) -> Iterator[int]:
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    stop = threading.Event()

    def serve() -> None:
        with listener:
            listener.settimeout(0.2)
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                with suppress(OSError, ssl.SSLError):
                    if wrap is not None:
                        connection = wrap.wrap_socket(connection, server_side=True)
                    handle(connection)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        stop.set()
        thread.join(timeout=5)


def _reset(connection: socket.socket) -> None:
    linger = struct.pack("HH", 1, 0) if sys.platform == "win32" else struct.pack("ii", 1, 0)
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
    connection.close()


def _self_signed_context(directory: Path) -> ssl.SSLContext:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "server.crt"
    key_path = directory / "server.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context


def test_unresolvable_host_was_not_sent() -> None:
    error = _init_failure("https://presto-pay-sdk-test.invalid")
    assert error.request_not_sent
    assert not error.may_have_taken_effect


def test_closed_port_was_not_sent() -> None:
    with socket.create_server(("127.0.0.1", 0)) as probe:
        port = probe.getsockname()[1]
    error = _init_failure(f"http://127.0.0.1:{port}")
    assert error.request_not_sent
    assert not error.may_have_taken_effect


def test_blackholed_connect_was_not_sent() -> None:
    error = _init_failure("https://10.255.255.1", deadline=0.5)
    assert error.request_not_sent


def test_untrusted_certificate_was_not_sent(tmp_path: Path) -> None:
    received: list[bytes] = []

    def handle(connection: socket.socket) -> None:
        received.append(_read_request(connection))

    with _server(handle, wrap=_self_signed_context(tmp_path)) as port:
        error = _init_failure(f"https://127.0.0.1:{port}")
    assert error.request_not_sent
    assert not error.may_have_taken_effect
    assert received == []


def test_reset_after_the_body_arrived_may_have_taken_effect() -> None:
    received: list[bytes] = []

    def handle(connection: socket.socket) -> None:
        received.append(_read_request(connection))
        _reset(connection)

    with _server(handle) as port:
        error = _init_failure(f"http://127.0.0.1:{port}")
    assert b'"signature"' in received[0]
    assert not error.request_not_sent
    assert error.may_have_taken_effect
    assert error.reconcile_by is None


def test_response_that_never_comes_may_have_taken_effect() -> None:
    received: list[bytes] = []
    release = threading.Event()

    def handle(connection: socket.socket) -> None:
        received.append(_read_request(connection))
        release.wait(5)
        connection.close()

    with _server(handle) as port:
        error = _init_failure(f"http://127.0.0.1:{port}", deadline=0.5)
        release.set()
    assert b'"signature"' in received[0]
    assert not error.request_not_sent
    assert error.may_have_taken_effect
    assert "ReadTimeout" in str(error)
