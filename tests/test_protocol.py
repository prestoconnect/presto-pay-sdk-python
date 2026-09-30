from __future__ import annotations

import json
from typing import Any

import pytest

from conftest import (
    BASE_URL,
    MID,
    MRN,
    NOW,
    NOW_TS,
    TEST_CERT_PEM,
    TEST_PRIVATE_KEY,
    business_error,
    gateway_sign,
    init_success,
    signed_json,
    verifies_as_merchant,
)
from presto_pay import (
    PrestoPayApiError,
    PrestoPayConfigError,
    PrestoPayResponseError,
    PrestoPaySignatureError,
    load_presto_public_key,
    load_private_key,
)
from presto_pay._core.mapping import FieldReader, MappingError, to_camel, to_snake
from presto_pay._core.protocol import (
    CONTENT_TYPE,
    INIT,
    QUERY,
    REFUND,
    REVERSE,
    USER_AGENT,
    OperationSpec,
    PreparedRequest,
    ProtocolConfig,
    RawResponse,
    interpret,
    prepare,
)
from presto_pay.errors import ReconcileKey

WRITES = [INIT, REVERSE, REFUND]
ALL = [INIT, QUERY, REVERSE, REFUND]
RECONCILE: ReconcileKey = {"presto_mrn": MRN, "txn_ref_num": "order-123"}


PRIVATE_KEY = load_private_key(TEST_PRIVATE_KEY)
PRESTO_KEYS = (load_presto_public_key(TEST_CERT_PEM),)


def config(*, strict: bool = False, redact: bool = True) -> ProtocolConfig:
    return ProtocolConfig(
        base_url=BASE_URL,
        merchant_id=MID,
        private_key=PRIVATE_KEY,
        presto_public_keys=PRESTO_KEYS,
        strict=strict,
        redact_error_bodies=redact,
    )


def prepared(operation: OperationSpec = INIT, **fields: Any) -> PreparedRequest:
    body = {"prestoMrn": MRN, "txnRefNum": "order-123", **fields}
    return prepare(operation, body, config(), NOW, RECONCILE)


def respond(body: bytes | dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> RawResponse:
    raw = body if isinstance(body, bytes) else signed_json(body)
    return RawResponse(status=status, headers=headers or {}, body=raw)


def whole_body(reader: FieldReader) -> dict[str, Any]:
    return dict(reader.body)


def run(
    response: RawResponse, operation: OperationSpec = INIT, *, strict: bool = False, redact: bool = True
) -> dict[str, Any]:
    return interpret(prepared(operation), response, config(strict=strict, redact=redact), whole_body)


class TestPrepare:
    def test_adds_mid_ts_and_a_signature_the_gateway_can_verify(self) -> None:
        request = prepared(amount=1200, flag=True)
        body = json.loads(request.body)
        assert body["mid"] == MID
        assert body["ts"] == NOW_TS == request.ts
        assert verifies_as_merchant(body)

    def test_body_is_compact_utf8_without_ascii_escaping(self) -> None:
        request = prepared(displayDesc="Café 東京")
        assert "Café 東京".encode() in request.body
        assert b", " not in request.body
        assert b'": ' not in request.body

    def test_url_and_headers(self) -> None:
        request = prepared(QUERY)
        assert request.url == BASE_URL + "/v1/ext/payment/query"
        assert ("Content-Type", CONTENT_TYPE) in request.headers
        assert ("User-Agent", USER_AGENT) in request.headers
        assert USER_AGENT.startswith("presto-pay-sdk-python/")

    @pytest.mark.parametrize("reserved", ["mid", "ts", "signature"])
    def test_sdk_owned_fields_cannot_be_passed(self, reserved: str) -> None:
        with pytest.raises(PrestoPayConfigError, match=reserved):
            prepare(QUERY, {reserved: "x"}, config(), NOW)

    def test_unpaired_surrogate_is_a_named_field_error(self) -> None:
        with pytest.raises(PrestoPayConfigError) as caught:
            prepared(displayDesc="bad \ud800")
        assert caught.value.field == "display_desc"

    def test_every_attempt_gets_a_fresh_ts(self) -> None:
        first = prepare(QUERY, {"prestoMrn": MRN}, config(), NOW)
        second = prepare(QUERY, {"prestoMrn": MRN}, config(), NOW + 1.5)
        assert first.ts != second.ts
        assert first.signed_body["signature"] != second.signed_body["signature"]


class TestHttpErrors:
    def test_details_come_from_headers_case_insensitively(self) -> None:
        response = respond(b"<html>nope</html>", 400, {"X-HTTP-Error-Code": "E400", "X-Http-Error": "Bad request"})
        with pytest.raises(PrestoPayApiError) as caught:
            run(response)
        error = caught.value
        assert (error.kind, error.http_status, error.error_code, error.error_message) == (
            "http",
            400,
            "E400",
            "Bad request",
        )
        assert not error.may_have_taken_effect

    @pytest.mark.parametrize("operation", WRITES, ids=lambda op: op.name)
    def test_server_error_on_a_write_may_have_taken_effect(self, operation: OperationSpec) -> None:
        with pytest.raises(PrestoPayApiError) as caught:
            run(respond(b"", 502), operation)
        assert caught.value.may_have_taken_effect
        assert caught.value.reconcile_by == RECONCILE

    def test_server_error_on_query_did_not(self) -> None:
        with pytest.raises(PrestoPayApiError) as caught:
            run(respond(b"", 503), QUERY)
        assert not caught.value.may_have_taken_effect
        assert caught.value.reconcile_by is None

    def test_redirect_is_an_http_error(self) -> None:
        with pytest.raises(PrestoPayApiError, match="HTTP 302"):
            run(respond(b"", 302, {"location": "https://elsewhere"}))


class TestResponseOrder:
    @pytest.mark.parametrize("operation", ALL, ids=lambda op: op.name)
    def test_malformed_body(self, operation: OperationSpec) -> None:
        with pytest.raises(PrestoPayResponseError, match="malformed") as caught:
            run(respond(b"{not json"), operation)
        assert caught.value.may_have_taken_effect is operation.write

    def test_missing_signature(self) -> None:
        with pytest.raises(PrestoPaySignatureError, match="no signature") as caught:
            run(respond(json.dumps(init_success()).encode()))
        assert caught.value.source == "response"
        assert caught.value.may_have_taken_effect
        assert caught.value.canonical is not None

    def test_signature_is_checked_before_success(self) -> None:
        tampered = {**gateway_sign(business_error("1201", "Invalid input.")), "errorMessage": "changed"}
        with pytest.raises(PrestoPaySignatureError, match="does not verify"):
            run(respond(json.dumps(tampered).encode()), QUERY)

    @pytest.mark.parametrize("success", [None, "true", 1])
    def test_success_must_be_a_boolean(self, success: object) -> None:
        body = init_success(success=success)
        with pytest.raises(PrestoPayResponseError, match="boolean success"):
            run(respond(body))

    def test_success_absent(self) -> None:
        body = init_success()
        del body["success"]
        with pytest.raises(PrestoPayResponseError, match="boolean success"):
            run(respond(body))

    def test_mapping_failure_after_a_write_may_have_taken_effect(self) -> None:
        def needs_missing(reader: FieldReader) -> str:
            return reader.required_str("paymentRefNum")

        body = init_success(paymentRefNum="")
        with pytest.raises(PrestoPayResponseError, match="paymentRefNum") as caught:
            interpret(prepared(), respond(body), config(), needs_missing)
        assert caught.value.may_have_taken_effect

    def test_malformed_response_ts(self) -> None:
        with pytest.raises(PrestoPayResponseError, match="gateway timestamp"):
            run(respond(init_success(ts="2026-09-24")))

    def test_success(self) -> None:
        assert run(respond(init_success()))["paymentRefNum"] == "PP260924K4H3DSF"


class TestEcho:
    def test_presto_mrn_mismatch(self) -> None:
        with pytest.raises(PrestoPayResponseError, match="prestoMrn") as caught:
            run(respond(init_success(prestoMrn="PMOTHER")))
        assert caught.value.may_have_taken_effect

    def test_txn_ref_num_mismatch(self) -> None:
        with pytest.raises(PrestoPayResponseError, match="txnRefNum"):
            run(respond(init_success(txnRefNum="order-999")))

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_txn_ref_num_is_not_a_mismatch(self, value: str | None) -> None:
        run(respond(init_success(txnRefNum=value)))

    def test_missing_presto_mrn_is_a_mismatch(self) -> None:
        body = init_success()
        del body["prestoMrn"]
        with pytest.raises(PrestoPayResponseError, match="prestoMrn"):
            run(respond(body))


class TestBusinessErrors:
    def test_captured_shape_with_only_five_fields(self) -> None:
        with pytest.raises(PrestoPayApiError) as caught:
            run(respond(business_error("1201", "Invalid input.")))
        error = caught.value
        assert (error.kind, error.http_status, error.error_code, error.error_message) == (
            "business",
            200,
            "1201",
            "Invalid input.",
        )
        assert not error.may_have_taken_effect
        assert error.reconcile_by is None

    def test_duplicate_txn_ref_num_on_init_prompts_a_query(self) -> None:
        with pytest.raises(PrestoPayApiError) as caught:
            run(respond(business_error("1203", "Duplicate")))
        assert caught.value.may_have_taken_effect
        assert caught.value.reconcile_by == RECONCILE

    def test_duplicate_txn_ref_num_elsewhere_is_ordinary(self) -> None:
        with pytest.raises(PrestoPayApiError) as caught:
            run(respond(business_error("1203", "Duplicate")), REFUND)
        assert not caught.value.may_have_taken_effect

    def test_clock_skew_reports_the_observed_offset(self) -> None:
        with pytest.raises(PrestoPayApiError, match=r"15 minutes.*\+1200\.0s") as caught:
            run(respond(business_error("1005", "Expired", ts="20260924135756.056")))
        assert caught.value.clock_offset == pytest.approx(1200.0)

    @pytest.mark.parametrize("code", ["1006", "1007"])
    def test_signature_rejections_attach_the_request_canonical(self, code: str) -> None:
        with pytest.raises(PrestoPayApiError, match="could not verify the request signature") as caught:
            run(respond(business_error(code, "Invalid signature")))
        canonical = caught.value.canonical
        assert canonical is not None
        assert f"{MID}:{MRN}:{NOW_TS}:order-123" == canonical


PERSONAL_FIELDS = {
    "paymentDetails": json.dumps([{"amount": 1, "cardBin": "411111", "cardSummary": "4111********1111"}]),
    "receiptEmail": "buyer@example.com",
}


class TestRedaction:
    def test_bodies_are_redacted_by_default(self) -> None:
        body = business_error("1201", "Invalid input.") | PERSONAL_FIELDS
        with pytest.raises(PrestoPayApiError) as caught:
            run(respond(body))
        raw = caught.value.raw_body or ""
        assert "411111" not in raw
        assert "buyer@example.com" not in raw
        assert "Invalid input." in raw
        assert "411111" not in str(caught.value) + repr(caught.value)

    def test_opting_out_shows_the_full_body(self) -> None:
        body = business_error("1201", "Invalid input.") | PERSONAL_FIELDS
        with pytest.raises(PrestoPayApiError) as caught:
            run(respond(body), redact=False)
        assert "411111" in (caught.value.raw_body or "")

    def test_request_canonical_is_redacted(self) -> None:
        request = prepare(INIT, {"prestoMrn": MRN, "receiptEmail": "buyer@example.com"}, config(), NOW, RECONCILE)
        with pytest.raises(PrestoPayApiError) as caught:
            interpret(request, respond(business_error("1006", "Invalid signature")), config(), whole_body)
        assert "buyer@example.com" not in (caught.value.canonical or "")
        assert "buyer@example.com" in request.canonical

    def test_unparseable_body_is_not_echoed(self) -> None:
        with pytest.raises(PrestoPayResponseError) as caught:
            run(respond(b"secret-ish text"))
        assert "secret-ish" not in (caught.value.raw_body or "")


class TestFieldReader:
    def test_empty_string_and_null_are_one_condition(self) -> None:
        reader = FieldReader({"a": "", "b": None}, strict=True)
        assert reader.optional_str("a") is None
        assert reader.optional_str("b") is None
        assert reader.optional_str("absent") is None

    def test_stray_number_is_coerced_unless_strict(self) -> None:
        assert FieldReader({"a": 12, "b": True}, strict=False).optional_str("a") == "12"
        assert FieldReader({"b": True}, strict=False).optional_str("b") == "true"
        with pytest.raises(MappingError):
            FieldReader({"a": 12}, strict=True).optional_str("a")

    def test_numeric_text_is_coerced_unless_strict(self) -> None:
        assert FieldReader({"a": "-12"}, strict=False).optional_int("a") == -12
        with pytest.raises(MappingError):
            FieldReader({"a": "12"}, strict=True).optional_int("a")
        with pytest.raises(MappingError):
            FieldReader({"a": "--12"}, strict=False).optional_int("a")

    def test_stringified_lists(self) -> None:
        reader = FieldReader({"a": "[]", "b": '[{"x":1}]', "c": None, "d": "", "e": "[1]", "f": "{}"}, strict=False)
        assert reader.list_of_objects("a") == []
        assert reader.list_of_objects("b") == [{"x": 1}]
        assert reader.list_of_objects("c") == []
        assert reader.list_of_objects("d") == []
        assert reader.list_of_objects("absent") == []
        with pytest.raises(MappingError):
            reader.list_of_objects("e")
        with pytest.raises(MappingError):
            reader.list_of_objects("f")

    @pytest.mark.parametrize(
        ("snake", "camel"),
        [("txn_ref_num", "txnRefNum"), ("presto_mrn", "prestoMrn"), ("mid", "mid"), ("device_ip", "deviceIp")],
    )
    def test_name_mapping_round_trips(self, snake: str, camel: str) -> None:
        assert to_camel(snake) == camel
        assert to_snake(camel) == snake
