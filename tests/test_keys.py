from __future__ import annotations

from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.serialization import pkcs12

from conftest import PRESTO_STAGING_CERT, TEST_CERT_DER, TEST_CERT_PEM, TEST_PRIVATE_KEY, TEST_PUBLIC_KEY
from presto_pay import PrestoPayConfigError, PrivateKey, load_presto_public_key, load_private_key
from presto_pay._core.crypto import sign, verify
from presto_pay._core.keys import coerce_public_keys

PEM = TEST_PRIVATE_KEY.read_bytes()


def _rsa() -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(PEM, None)
    assert isinstance(key, rsa.RSAPrivateKey)
    return key


def _p12(password: bytes | None) -> bytes:
    certificate = x509.load_pem_x509_certificate(TEST_CERT_PEM.read_bytes())
    encryption: serialization.KeySerializationEncryption = (
        serialization.BestAvailableEncryption(password) if password else serialization.NoEncryption()
    )
    return pkcs12.serialize_key_and_certificates(b"merchant", _rsa(), certificate, None, encryption)


def _signs_like_the_test_key(key: PrivateKey) -> bool:
    return verify([load_presto_public_key(TEST_PUBLIC_KEY)], "probe", sign(key, "probe"))


@pytest.mark.parametrize("source", [PEM.decode("ascii"), PEM, TEST_PRIVATE_KEY], ids=["str", "bytes", "path"])
def test_pkcs8_pem(source: str | bytes | Path) -> None:
    assert _signs_like_the_test_key(load_private_key(source))


def test_pkcs8_der() -> None:
    der = _rsa().private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    assert _signs_like_the_test_key(load_private_key(der))


def test_pkcs12_without_password(tmp_path: Path) -> None:
    path = tmp_path / "merchant.p12"
    path.write_bytes(_p12(None))
    assert _signs_like_the_test_key(load_private_key(path))


@pytest.mark.parametrize("password", ["s3cret", b"s3cret"])
def test_pkcs12_with_password(tmp_path: Path, password: str | bytes) -> None:
    path = tmp_path / "merchant.p12"
    path.write_bytes(_p12(b"s3cret"))
    assert _signs_like_the_test_key(load_private_key(path, password))


def test_pkcs12_wrong_password_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "merchant.p12"
    path.write_bytes(_p12(b"s3cret"))
    with pytest.raises(PrestoPayConfigError, match=r"merchant\.p12.*password is wrong") as caught:
        load_private_key(path, "nope")
    assert caught.value.field == "private_key"


def test_pkcs12_missing_password_hints_at_it(tmp_path: Path) -> None:
    path = tmp_path / "merchant.p12"
    path.write_bytes(_p12(b"s3cret"))
    with pytest.raises(PrestoPayConfigError, match="private_key_password"):
        load_private_key(path)


def test_encrypted_pem() -> None:
    encrypted = _rsa().private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"pw"),
    )
    assert _signs_like_the_test_key(load_private_key(encrypted, "pw"))
    with pytest.raises(PrestoPayConfigError, match="encrypted; pass private_key_password"):
        load_private_key(encrypted)
    with pytest.raises(PrestoPayConfigError, match="password is wrong"):
        load_private_key(encrypted, "wrong")


@pytest.mark.parametrize("source", [TEST_CERT_PEM, TEST_CERT_DER], ids=["pem", "der"])
def test_certificate_passed_as_private_key(source: Path) -> None:
    with pytest.raises(PrestoPayConfigError, match="is a certificate, not a private key"):
        load_private_key(source)


def test_public_key_passed_as_private_key() -> None:
    with pytest.raises(PrestoPayConfigError, match="is a public key"):
        load_private_key(TEST_PUBLIC_KEY)


def test_truncated_pem() -> None:
    with pytest.raises(PrestoPayConfigError, match="truncated or corrupted"):
        load_private_key(PEM[: len(PEM) // 2] + b"\n-----END PRIVATE KEY-----\n")


def test_non_rsa_key() -> None:
    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    with pytest.raises(PrestoPayConfigError, match="not an RSA private key"):
        load_private_key(pem)


def test_short_rsa_key() -> None:
    pem = rsa.generate_private_key(public_exponent=65537, key_size=1024).private_bytes(  # noqa: S505
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    with pytest.raises(PrestoPayConfigError, match="RSA-1024; at least 2048"):
        load_private_key(pem)


def test_path_as_str_is_not_guessed() -> None:
    with pytest.raises(PrestoPayConfigError, match=r"pathlib\.Path"):
        load_private_key(str(TEST_PRIVATE_KEY))


def test_missing_file_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(PrestoPayConfigError, match=r"missing\.pem"):
        load_private_key(tmp_path / "missing.pem")


def test_private_key_repr_carries_no_key_material() -> None:
    text = repr(load_private_key(TEST_PRIVATE_KEY))
    assert "rsa_bits=2048" in text
    assert "MII" not in text


@pytest.mark.parametrize(
    "source",
    [
        TEST_CERT_PEM,
        TEST_CERT_DER,
        TEST_PUBLIC_KEY,
        TEST_CERT_PEM.read_text(encoding="ascii"),
        TEST_CERT_DER.read_bytes(),
    ],
    ids=["cert-pem", "cert-der", "spki-pem", "cert-pem-text", "cert-der-bytes"],
)
def test_presto_public_key_encodings(source: str | bytes | Path) -> None:
    key = load_presto_public_key(source)
    assert key.fingerprint == load_presto_public_key(TEST_PUBLIC_KEY).fingerprint


def test_presto_staging_certificate_loads() -> None:
    assert load_presto_public_key(PRESTO_STAGING_CERT).key_size >= 2048


def test_private_key_passed_as_presto_key() -> None:
    with pytest.raises(PrestoPayConfigError, match="is a private key"):
        load_presto_public_key(TEST_PRIVATE_KEY)


def test_garbage_der_public_key() -> None:
    with pytest.raises(PrestoPayConfigError, match="neither a DER certificate nor a DER public key"):
        load_presto_public_key(b"\x30\x03\x02\x01\x00")


def test_public_key_list_for_rotation() -> None:
    keys = coerce_public_keys([PRESTO_STAGING_CERT, TEST_CERT_PEM])
    assert len(keys) == 2
    assert coerce_public_keys(TEST_CERT_PEM)[0].fingerprint == keys[1].fingerprint


def test_empty_public_key_list() -> None:
    with pytest.raises(PrestoPayConfigError, match="at least one"):
        coerce_public_keys([])
