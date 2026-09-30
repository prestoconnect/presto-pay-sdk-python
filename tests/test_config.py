from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from conftest import MID, TEST_CERT_DER, TEST_CERT_PEM, TEST_PRIVATE_KEY, client_options
from presto_pay import (
    AsyncPrestoPay,
    Environment,
    PrestoPay,
    PrestoPayConfigError,
    from_env,
)

PEM_TEXT = TEST_PRIVATE_KEY.read_text(encoding="ascii")
CERT_TEXT = TEST_CERT_PEM.read_text(encoding="ascii")


def env(**overrides: str) -> dict[str, str]:
    values = {
        "PRESTOPAY_ENV": "staging",
        "PRESTOPAY_MID": MID,
        "PRESTOPAY_PRIVATE_KEY": PEM_TEXT,
        "PRESTOPAY_PUBLIC_KEY": CERT_TEXT,
    }
    values.update(overrides)
    return {key: value for key, value in values.items() if value != "<unset>"}


class TestFromEnv:
    def test_pem_text(self) -> None:
        with from_env(env()) as presto:
            assert presto.merchant_id == MID
            assert presto.base_url == Environment.STAGING.base_url

    def test_files_including_a_pkcs12_keystore(self, tmp_path: Path) -> None:
        key = serialization.load_pem_private_key(TEST_PRIVATE_KEY.read_bytes(), None)
        certificate = x509.load_pem_x509_certificate(TEST_CERT_PEM.read_bytes())
        keystore = tmp_path / "merchant.p12"
        keystore.write_bytes(
            pkcs12.serialize_key_and_certificates(
                b"merchant",
                key,  # type: ignore[arg-type]
                certificate,
                None,
                serialization.BestAvailableEncryption(b"changeit"),
            )
        )
        values = env(
            PRESTOPAY_ENV="production",
            PRESTOPAY_PRIVATE_KEY="<unset>",
            PRESTOPAY_PUBLIC_KEY="<unset>",
            PRESTOPAY_PRIVATE_KEY_FILE=str(keystore),
            PRESTOPAY_PRIVATE_KEY_PASSWORD="changeit",
            PRESTOPAY_PUBLIC_KEY_FILE=str(TEST_CERT_DER),
        )
        with from_env(values) as presto:
            assert presto.base_url == Environment.PRODUCTION.base_url

    def test_one_line_pem_with_escaped_newlines(self) -> None:
        with from_env(env(PRESTOPAY_PRIVATE_KEY=PEM_TEXT.replace("\n", "\\n"))) as presto:
            assert presto.merchant_id == MID

    def test_explicit_base_url(self) -> None:
        with from_env(env(PRESTOPAY_ENV="<unset>", PRESTOPAY_BASE_URL="https://proxy.example/presto/")) as presto:
            assert presto.base_url == "https://proxy.example/presto"

    @pytest.mark.parametrize(
        ("overrides", "field", "message"),
        [
            ({"PRESTOPAY_ENV": "<unset>"}, "PRESTOPAY_ENV", "'staging' or 'production'"),
            ({"PRESTOPAY_ENV": "prod"}, "PRESTOPAY_ENV", "'staging' or 'production'"),
            ({"PRESTOPAY_BASE_URL": "https://x.example"}, "PRESTOPAY_ENV", "not both"),
            ({"PRESTOPAY_MID": ""}, "PRESTOPAY_MID", "not set"),
            ({"PRESTOPAY_PRIVATE_KEY": "<unset>"}, "PRESTOPAY_PRIVATE_KEY", "_FILE is not set"),
            ({"PRESTOPAY_PRIVATE_KEY_FILE": "/k.pem"}, "PRESTOPAY_PRIVATE_KEY", "not both"),
            ({"PRESTOPAY_PUBLIC_KEY": "<unset>"}, "PRESTOPAY_PUBLIC_KEY", "_FILE is not set"),
        ],
    )
    def test_misconfiguration_names_the_variable(self, overrides: dict[str, str], field: str, message: str) -> None:
        with pytest.raises(PrestoPayConfigError, match=message) as caught:
            from_env(env(**overrides))
        assert caught.value.field == field

    @pytest.mark.anyio
    async def test_async_client(self) -> None:
        async with AsyncPrestoPay.from_env(env(), deadline=5.0) as presto:
            assert presto.merchant_id == MID

    def test_options_pass_through(self) -> None:
        http = httpx.Client()
        with PrestoPay.from_env(env(), http_client=http, strict=True) as presto:
            assert presto._protocol.strict
            assert presto._http is http
        assert not http.is_closed
        http.close()


class TestConstructor:
    def test_key_material_is_parsed_eagerly(self) -> None:
        with pytest.raises(PrestoPayConfigError, match="private_key"):
            PrestoPay(**client_options(private_key="-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"))

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"merchant_id": ""}, "merchant_id"),
            ({"deadline": 0}, "deadline"),
            ({"deadline": True}, "deadline"),
            ({"environment": "prod"}, "environment"),
            ({"presto_public_key": []}, "presto_public_key"),
        ],
    )
    def test_invalid_options(self, overrides: dict[str, Any], field: str) -> None:
        with pytest.raises(PrestoPayConfigError) as caught:
            PrestoPay(**client_options(**overrides))
        assert caught.value.field == field

    @pytest.mark.parametrize(
        "url",
        ["http://gateway.example", "ftp://gateway.example", "https://", "https://x.example/?a=1", "gateway.example"],
    )
    def test_base_url_must_be_https(self, url: str) -> None:
        with pytest.raises(PrestoPayConfigError, match=r"https|base URL"):
            Environment(url)

    @pytest.mark.parametrize("url", ["http://127.0.0.1:8080", "http://localhost:9000/", "http://[::1]:8080"])
    def test_plain_http_is_allowed_for_loopback(self, url: str) -> None:
        assert not Environment(url).base_url.endswith("/")

    def test_well_known_environments(self) -> None:
        assert Environment.STAGING.base_url == "https://presto-stg-ext.enovax.com"
        assert Environment.PRODUCTION.base_url == "https://pay-ext.prestouniverse.com"

    def test_repr_carries_no_key_material(self) -> None:
        with PrestoPay(**client_options()) as presto:
            assert repr(presto) == f"PrestoPay(merchant_id='{MID}', base_url='https://gateway.test')"
