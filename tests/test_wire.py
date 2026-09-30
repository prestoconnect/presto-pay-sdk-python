from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY
from presto_pay import canonicalize, format_gateway_timestamp, load_presto_public_key, load_private_key
from presto_pay._core.canonical import BodyError, canonical_string, parse_body
from presto_pay._core.crypto import sign, verify


def test_true_renders_as_true_not_as_the_int_it_subclasses() -> None:
    assert canonical_string({"a": True, "b": 1, "c": False, "d": 0}) == "true:1:false:0"


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_constants_are_rejected(token: str) -> None:
    with pytest.raises(BodyError, match="not valid JSON"):
        parse_body('{"amount":' + token + "}")


@pytest.mark.parametrize("token", ["1200.0", "1e400", "1E2", "12.5", "-0.0"])
def test_every_float_spelling_is_rejected(token: str) -> None:
    with pytest.raises(BodyError, match="non-integer"):
        parse_body('{"amount":' + token + "}")


def test_integer_bound_is_inclusive() -> None:
    assert parse_body('{"a":-9007199254740991}') == {"a": -9007199254740991}
    with pytest.raises(BodyError, match="outside"):
        parse_body('{"a":9007199254740992}')


def test_invalid_utf8_decodes_with_replacement() -> None:
    assert parse_body(b'{"a":"caf\xff"}') == {"a": "caf�"}


def test_duplicate_keys_resolve_last_wins() -> None:
    assert parse_body('{"a":"1","a":"2"}') == {"a": "2"}


def test_signature_key_is_excluded_wherever_it_sorts() -> None:
    assert canonicalize('{"signature":"x","sa":"1","sz":"2"}') == "1:2"


def test_timestamp_uses_plus_eight_whatever_the_input_zone() -> None:
    new_york_winter = datetime(2026, 1, 1, 10, 0, 0, 7000, tzinfo=timezone(timedelta(hours=-5)))
    assert format_gateway_timestamp(new_york_winter) == "20260101230000.007"


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError, match="aware"):
        format_gateway_timestamp(datetime(2026, 1, 1))


def _signature(canonical: str) -> str:
    return sign(load_private_key(TEST_PRIVATE_KEY), canonical)


def test_signature_with_embedded_newline_is_a_failed_verification() -> None:
    signature = _signature("abc")
    broken = signature[:10] + "\n" + signature[10:]
    assert base64.b64decode(broken) == base64.b64decode(signature)
    assert not verify([load_presto_public_key(TEST_PUBLIC_KEY)], "abc", broken)


@pytest.mark.parametrize("signature", ["", "!!!!", "YWJj", "not base64 at all", 12345, None])
def test_malformed_signature_is_a_failed_verification(signature: object) -> None:
    assert not verify([load_presto_public_key(TEST_PUBLIC_KEY)], "abc", signature)


def test_unencodable_canonical_is_a_failed_verification() -> None:
    assert not verify([load_presto_public_key(TEST_PUBLIC_KEY)], "\ud800", _signature("abc"))


def test_any_of_several_keys_may_verify() -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    other_pem = other.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    keys = [load_presto_public_key(other_pem), load_presto_public_key(TEST_PUBLIC_KEY)]
    assert verify(keys, "abc", _signature("abc"))
    assert not verify(keys[:1], "abc", _signature("abc"))
