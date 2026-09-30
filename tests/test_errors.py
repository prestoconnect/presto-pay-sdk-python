from __future__ import annotations

import pytest

from presto_pay import (
    PrestoPayApiError,
    PrestoPayConfigError,
    PrestoPayError,
    PrestoPayResponseError,
    PrestoPaySignatureError,
    PrestoPayTransportError,
    may_have_succeeded,
)


def _api_error(*, may_have_taken_effect: bool) -> PrestoPayApiError:
    return PrestoPayApiError(
        "Gateway returned HTTP 502 for init",
        operation="init",
        kind="http",
        http_status=502,
        error_code=None,
        error_message=None,
        raw_body='{"cardBin":"411111"}',
        may_have_taken_effect=may_have_taken_effect,
        reconcile_by={"presto_mrn": "PM1", "txn_ref_num": "order-1"},
    )


def test_every_error_is_a_presto_pay_error() -> None:
    for cls in (
        PrestoPayConfigError,
        PrestoPayTransportError,
        PrestoPayApiError,
        PrestoPaySignatureError,
        PrestoPayResponseError,
    ):
        assert issubclass(cls, PrestoPayError)


def test_str_and_repr_never_carry_the_body() -> None:
    error = _api_error(may_have_taken_effect=True)
    assert "411111" not in str(error)
    assert "411111" not in repr(error)
    assert str(error) == "Gateway returned HTTP 502 for init"


def test_reconcile_key_travels_only_with_an_ambiguous_outcome() -> None:
    assert _api_error(may_have_taken_effect=True).reconcile_by == {"presto_mrn": "PM1", "txn_ref_num": "order-1"}
    assert _api_error(may_have_taken_effect=False).reconcile_by is None


def test_may_have_succeeded() -> None:
    assert may_have_succeeded(_api_error(may_have_taken_effect=True))
    assert not may_have_succeeded(_api_error(may_have_taken_effect=False))
    assert not may_have_succeeded(ValueError("unrelated"))


def test_config_error_names_its_field() -> None:
    error = PrestoPayConfigError("amount must be an int", field="amount")
    assert error.field == "amount"
    assert error.operation == "config"
    assert not error.may_have_taken_effect
    with pytest.raises(PrestoPayError):
        raise error
