from __future__ import annotations

import re

import pytest

from conftest import SPEC
from presto_pay.constants import (
    ErrorCode,
    EventCode,
    PaymentMethod,
    PaymentStatus,
    RefundStatus,
    ReversalStatus,
    TxnType,
    _WireCode,
)

CONTRACT = (SPEC / "wire-contract.md").read_text(encoding="utf-8")


def _bullet(label: str) -> set[str]:
    match = re.search(r"\*\*" + re.escape(label) + r"\*\*(.*?)(?:\*\*[A-Z][a-z ]+:\*\*|\n\n|\n- )", CONTRACT, re.S)
    assert match, label
    return set(re.findall(r"`([^`]+)`", match.group(1)))


def _values(enum: type[_WireCode]) -> set[str]:
    return {member.value for member in enum}


@pytest.mark.parametrize(
    ("enum", "label"),
    [
        (PaymentStatus, "Payment status:"),
        (ReversalStatus, "Reversal status:"),
        (RefundStatus, "Refund status:"),
        (TxnType, "Transaction type:"),
    ],
)
def test_code_list_matches_the_contract(enum: type[_WireCode], label: str) -> None:
    assert _values(enum) == _bullet(label)


def test_payment_methods_match_the_contract() -> None:
    section = CONTRACT.split("- **Payment method**", 1)[1].split("\n\n", 1)[0]
    assert _values(PaymentMethod) == set(re.findall(r"`([^`]+)`", section))


def test_event_codes_match_the_contract() -> None:
    section = CONTRACT.split("Event codes, open-ended", 1)[1].split(". For", 1)[0]
    assert _values(EventCode) == set(re.findall(r"`([^`]+)`", section))


def test_error_codes_match_the_contract() -> None:
    section = CONTRACT.split("Full list **[U]**:", 1)[1].split("\n## ", 1)[0]
    listed = set(re.findall(r"\b(1[0-9]{3})\b", section))
    observed_elsewhere = {"1242"}
    assert "`1242`" in CONTRACT
    assert _values(ErrorCode) == listed | observed_elsewhere


def test_members_are_plain_strings() -> None:
    status: str = "Authorised"
    assert status == PaymentStatus.AUTHORISED
    assert f"{PaymentMethod.PM_PG_CARD}" == "PmPgCard"


def test_lookup_by_wire_value() -> None:
    assert PaymentMethod("UnionPayQR") is PaymentMethod.UNION_PAY_QR
    assert PaymentMethod.try_parse("Subwallet_NearU") is PaymentMethod.SUBWALLET_NEAR_U
    assert PaymentStatus.try_parse("SomethingNew") is None
    assert PaymentStatus.try_parse(None) is None
