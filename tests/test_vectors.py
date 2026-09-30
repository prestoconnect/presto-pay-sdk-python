from __future__ import annotations

import json
from datetime import UTC, timedelta
from typing import Any

import pytest

from conftest import KEYS, SPEC, TEST_CERT_DER, TEST_CERT_PEM, TEST_PRIVATE_KEY, TEST_PUBLIC_KEY, VECTORS, load_vectors
from presto_pay import canonicalize, load_presto_public_key, load_private_key, parse_gateway_timestamp
from presto_pay._core.crypto import sign, verify
from presto_pay._core.timestamp import format_epoch_millis, to_epoch_millis

CANONICAL = load_vectors("canonical.json")["cases"]
SIGNATURES = load_vectors("signatures.json")
TIMESTAMPS = load_vectors("timestamps.json")

CONSUMED_VECTOR_FILES = {"canonical.json", "signatures.json", "timestamps.json", "refund-policy.json"}


def _ids(case: dict[str, Any]) -> str:
    name: str = case["name"]
    return name


def _body_text(case: dict[str, Any]) -> str:
    if "bodyRaw" in case:
        text: str = case["bodyRaw"]
        return text
    return json.dumps(case["body"], ensure_ascii=False)


def test_every_vector_file_has_a_harness() -> None:
    present = {path.name for path in VECTORS.glob("*.json")}
    assert present - CONSUMED_VECTOR_FILES == set(), "a new spec vector file needs a test harness here"


def test_vendored_spec_records_its_source_commit() -> None:
    commit = (SPEC / ".source-commit").read_text(encoding="ascii").strip()
    assert len(commit) == 40
    assert all(c in "0123456789abcdef" for c in commit)


@pytest.mark.parametrize("case", [c for c in CANONICAL if "canonical" in c], ids=_ids)
def test_canonical_string(case: dict[str, Any]) -> None:
    assert canonicalize(_body_text(case)) == case["canonical"]
    assert canonicalize(_body_text(case).encode("utf-8")) == case["canonical"]


@pytest.mark.parametrize("case", [c for c in CANONICAL if "reject" in c], ids=_ids)
def test_canonical_rejects(case: dict[str, Any]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - vectors match on the fact of rejection, not the wording
        canonicalize(_body_text(case))


@pytest.mark.parametrize("case", [c for c in CANONICAL if "signature" in c], ids=_ids)
def test_captured_gateway_signature_verifies(case: dict[str, Any]) -> None:
    key = load_presto_public_key(SPEC / case["verifyWith"])
    assert verify([key], case["canonical"], case["signature"])


@pytest.mark.parametrize("case", [c for c in CANONICAL if "signature" in c], ids=_ids)
def test_captured_gateway_signature_rejects_a_tampered_body(case: dict[str, Any]) -> None:
    key = load_presto_public_key(SPEC / case["verifyWith"])
    assert not verify([key], case["canonical"] + " ", case["signature"])


def test_signature_vectors_name_the_test_key() -> None:
    assert SPEC / SIGNATURES["key"] == TEST_PRIVATE_KEY
    assert (KEYS / "test-merchant-key.pem").exists()


@pytest.mark.parametrize("case", SIGNATURES["cases"], ids=_ids)
def test_signing_reproduces_signature_vector(case: dict[str, Any]) -> None:
    assert sign(load_private_key(TEST_PRIVATE_KEY), case["canonical"]) == case["signature"]


@pytest.mark.parametrize("case", SIGNATURES["cases"], ids=_ids)
@pytest.mark.parametrize(
    "key_path", [TEST_PUBLIC_KEY, TEST_CERT_PEM, TEST_CERT_DER], ids=["spki", "cert-pem", "cert-der"]
)
def test_signature_vector_verifies(case: dict[str, Any], key_path: Any) -> None:
    assert verify([load_presto_public_key(key_path)], case["canonical"], case["signature"])


@pytest.mark.parametrize("case", TIMESTAMPS["format"], ids=_ids)
def test_timestamp_formats(case: dict[str, Any]) -> None:
    assert format_epoch_millis(case["epochMillis"]) == case["ts"]


@pytest.mark.parametrize("case", TIMESTAMPS["format"], ids=_ids)
def test_timestamp_parses(case: dict[str, Any]) -> None:
    parsed = parse_gateway_timestamp(case["ts"])
    assert to_epoch_millis(parsed) == case["epochMillis"]
    utc = parsed.astimezone(UTC)
    assert f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z" == case["utc"]
    assert parsed.utcoffset() == timedelta(hours=8)


@pytest.mark.parametrize("case", TIMESTAMPS["parse"], ids=_ids)
def test_timestamp_parse_rejects(case: dict[str, Any]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        parse_gateway_timestamp(case["ts"])
