from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12

from presto_pay.errors import PrestoPayConfigError

MIN_KEY_BITS = 2048

KeySource = str | bytes | os.PathLike[str]
Password = str | bytes | None


class PrivateKey:
    __slots__ = ("_key", "source")

    def __init__(self, key: rsa.RSAPrivateKey, source: str = "private_key") -> None:
        self._key = _require_rsa_private(key, source, "private_key")
        self.source = source

    @property
    def key_size(self) -> int:
        return self._key.key_size

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data, padding.PKCS1v15(), hashes.SHA256())

    def __repr__(self) -> str:
        return f"PrivateKey(source={self.source!r}, rsa_bits={self.key_size})"


class PrestoPublicKey:
    __slots__ = ("_key", "fingerprint", "source")

    def __init__(self, key: rsa.RSAPublicKey, source: str = "presto_public_key") -> None:
        self._key = _require_rsa_public(key, source, "presto_public_key")
        self.source = source
        spki = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.fingerprint = hashlib.sha256(spki).hexdigest()

    @property
    def key_size(self) -> int:
        return self._key.key_size

    def verify(self, signature: bytes, data: bytes) -> bool:
        try:
            self._key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature:
            return False
        return True

    def __repr__(self) -> str:
        return f"PrestoPublicKey(source={self.source!r}, sha256={self.fingerprint[:16]}…)"


PrivateKeyInput = PrivateKey | KeySource
PublicKeyInput = PrestoPublicKey | KeySource


def load_private_key(source: KeySource, password: Password = None, *, field: str = "private_key") -> PrivateKey:
    data, label = _read(source, field)
    secret = password.encode("utf-8") if isinstance(password, str) else password
    if b"-----BEGIN" in data:
        key = _parse_pem_private(data, secret, label, field)
    elif isinstance(source, str):
        raise PrestoPayConfigError(
            f"{label} is text but not PEM; pass a pathlib.Path to read a key file, or bytes for DER or PKCS#12",
            field=field,
        )
    else:
        key = _parse_binary_private(data, secret, label, field)
    return PrivateKey(_require_rsa_private(key, label, field), label)


def coerce_private_key(value: PrivateKeyInput, password: Password = None) -> PrivateKey:
    if isinstance(value, PrivateKey):
        return value
    return load_private_key(value, password)


def load_presto_public_key(source: KeySource, *, field: str = "presto_public_key") -> PrestoPublicKey:
    data, label = _read(source, field)
    if b"-----BEGIN" in data:
        key = _parse_pem_public(data, label, field)
    elif isinstance(source, str):
        raise PrestoPayConfigError(
            f"{label} is text but not PEM; pass a pathlib.Path to read a certificate file, or bytes for DER",
            field=field,
        )
    else:
        key = _parse_der_public(data, label, field)
    return PrestoPublicKey(_require_rsa_public(key, label, field), label)


def coerce_public_keys(
    value: PublicKeyInput | Sequence[PublicKeyInput], *, field: str = "presto_public_key"
) -> tuple[PrestoPublicKey, ...]:
    items: Sequence[PublicKeyInput] = (
        [value] if isinstance(value, PrestoPublicKey | str | bytes | os.PathLike) else value
    )
    keys = tuple(
        item if isinstance(item, PrestoPublicKey) else load_presto_public_key(item, field=field) for item in items
    )
    if not keys:
        raise PrestoPayConfigError(f"{field} needs at least one Presto public key", field=field)
    return keys


def _read(source: KeySource, field: str) -> tuple[bytes, str]:
    if isinstance(source, os.PathLike):
        path = Path(source)
        try:
            return path.read_bytes(), str(path)
        except OSError as exc:
            raise PrestoPayConfigError(f"{field}: cannot read {path}: {exc.strerror or exc}", field=field) from exc
    if isinstance(source, str):
        return source.encode("utf-8"), field
    if isinstance(source, bytes):
        return source, field
    raise PrestoPayConfigError(
        f"{field} must be PEM text, bytes, or a path, not {type(source).__name__}",
        field=field,
    )


def _parse_pem_private(data: bytes, password: bytes | None, label: str, field: str) -> object:
    if b"PRIVATE KEY-----" not in data:
        if b"CERTIFICATE-----" in data:
            raise PrestoPayConfigError(
                f"{label} is a certificate, not a private key; pass the merchant private key or the onboarding .p12",
                field=field,
            )
        if b"PUBLIC KEY-----" in data:
            raise PrestoPayConfigError(
                f"{label} is a public key, not a private key; pass the merchant private key", field=field
            )
        raise PrestoPayConfigError(f"{label} has no PRIVATE KEY block", field=field)
    encrypted = b"ENCRYPTED PRIVATE KEY" in data or b"Proc-Type: 4,ENCRYPTED" in data
    if encrypted and password is None:
        raise PrestoPayConfigError(f"{label} is encrypted; pass private_key_password", field=field)
    try:
        return serialization.load_pem_private_key(data, password if encrypted else None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        reason = "the password is wrong or the PEM is corrupted" if encrypted else "it is truncated or corrupted"
        raise PrestoPayConfigError(f"{label} could not be read as a PEM private key: {reason}", field=field) from exc


def _parse_binary_private(data: bytes, password: bytes | None, label: str, field: str) -> object:
    with suppress(ValueError, TypeError, UnsupportedAlgorithm):
        return serialization.load_der_private_key(data, password)
    # An unencrypted key with a password set (a shared PRESTOPAY_PRIVATE_KEY_PASSWORD, say) is still usable, just as
    # it is for PEM; without this retry it would fall through to PKCS#12 and be reported as a wrong password.
    if password is not None:
        with suppress(ValueError, TypeError, UnsupportedAlgorithm):
            return serialization.load_der_private_key(data, None)
    if _is_der_certificate(data):
        raise PrestoPayConfigError(
            f"{label} is a certificate, not a private key; pass the merchant private key or the onboarding .p12",
            field=field,
        )
    try:
        key, _certificate, _chain = pkcs12.load_key_and_certificates(data, password)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        hint = "the password is wrong" if password is not None else "it may need private_key_password"
        raise PrestoPayConfigError(
            f"{label} is not a readable DER private key or PKCS#12 keystore; {hint}", field=field
        ) from exc
    if key is None:
        raise PrestoPayConfigError(f"{label} is a PKCS#12 keystore with no private key in it", field=field)
    return key


def _is_der_certificate(data: bytes) -> bool:
    try:
        x509.load_der_x509_certificate(data)
    except ValueError:
        return False
    return True


def _parse_pem_public(data: bytes, label: str, field: str) -> object:
    if b"PRIVATE KEY-----" in data:
        raise PrestoPayConfigError(
            f"{label} is a private key; pass Presto's certificate (or its public key) instead", field=field
        )
    try:
        if b"CERTIFICATE-----" in data:
            return x509.load_pem_x509_certificate(data).public_key()
        if b"PUBLIC KEY-----" in data:
            return serialization.load_pem_public_key(data)
    except (ValueError, UnsupportedAlgorithm) as exc:
        raise PrestoPayConfigError(f"{label} could not be parsed; it is truncated or corrupted", field=field) from exc
    raise PrestoPayConfigError(f"{label} has no CERTIFICATE or PUBLIC KEY block", field=field)


def _parse_der_public(data: bytes, label: str, field: str) -> object:
    with suppress(ValueError):
        return x509.load_der_x509_certificate(data).public_key()
    try:
        return serialization.load_der_public_key(data)
    except (ValueError, UnsupportedAlgorithm) as exc:
        raise PrestoPayConfigError(f"{label} is neither a DER certificate nor a DER public key", field=field) from exc


def _require_rsa_private(key: object, label: str, field: str) -> rsa.RSAPrivateKey:
    if not isinstance(key, rsa.RSAPrivateKey):
        raise PrestoPayConfigError(f"{label} is not an RSA private key; Presto signatures are RSA", field=field)
    if key.key_size < MIN_KEY_BITS:
        raise PrestoPayConfigError(f"{label} is RSA-{key.key_size}; at least {MIN_KEY_BITS} bits required", field=field)
    return key


def _require_rsa_public(key: object, label: str, field: str) -> rsa.RSAPublicKey:
    if not isinstance(key, rsa.RSAPublicKey):
        raise PrestoPayConfigError(f"{label} is not an RSA public key; Presto signatures are RSA", field=field)
    if key.key_size < MIN_KEY_BITS:
        raise PrestoPayConfigError(f"{label} is RSA-{key.key_size}; at least {MIN_KEY_BITS} bits required", field=field)
    return key
