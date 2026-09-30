from __future__ import annotations

from typing import Literal, Required, TypedDict

Operation = Literal["init", "query", "reverse", "refund", "raw", "webhook", "config"]
Source = Literal["response", "webhook"]
ApiErrorKind = Literal["http", "business"]


class ReconcileKey(TypedDict, total=False):
    presto_mrn: Required[str]
    txn_ref_num: str
    payment_ref_num: str


class PrestoPayError(Exception):
    operation: Operation
    may_have_taken_effect: bool
    reconcile_by: ReconcileKey | None

    def __init__(
        self,
        message: str,
        *,
        operation: Operation,
        may_have_taken_effect: bool = False,
        reconcile_by: ReconcileKey | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.may_have_taken_effect = may_have_taken_effect
        self.reconcile_by = reconcile_by if may_have_taken_effect else None

    @property
    def message(self) -> str:
        return str(self.args[0]) if self.args else ""

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r}, operation={self.operation!r})"


class PrestoPayConfigError(PrestoPayError):
    field: str | None

    def __init__(self, message: str, *, field: str | None = None, operation: Operation = "config") -> None:
        super().__init__(message, operation=operation)
        self.field = field

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r}, field={self.field!r})"


class PrestoPayTransportError(PrestoPayError):
    request_not_sent: bool

    def __init__(
        self,
        message: str,
        *,
        operation: Operation,
        request_not_sent: bool,
        may_have_taken_effect: bool,
        reconcile_by: ReconcileKey | None = None,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            may_have_taken_effect=may_have_taken_effect,
            reconcile_by=reconcile_by,
        )
        self.request_not_sent = request_not_sent


class PrestoPayApiError(PrestoPayError):
    kind: ApiErrorKind
    http_status: int
    error_code: str | None
    error_message: str | None
    raw_body: str | None
    canonical: str | None
    clock_offset: float | None

    def __init__(
        self,
        message: str,
        *,
        operation: Operation,
        kind: ApiErrorKind,
        http_status: int,
        error_code: str | None,
        error_message: str | None,
        raw_body: str | None,
        may_have_taken_effect: bool = False,
        reconcile_by: ReconcileKey | None = None,
        canonical: str | None = None,
        clock_offset: float | None = None,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            may_have_taken_effect=may_have_taken_effect,
            reconcile_by=reconcile_by,
        )
        self.kind = kind
        self.http_status = http_status
        self.error_code = error_code
        self.error_message = error_message
        self.raw_body = raw_body
        self.canonical = canonical
        self.clock_offset = clock_offset

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}({self.message!r}, operation={self.operation!r}, kind={self.kind!r}, "
            f"http_status={self.http_status!r}, error_code={self.error_code!r})"
        )


class PrestoPaySignatureError(PrestoPayError):
    source: Source
    canonical: str | None

    def __init__(
        self,
        message: str,
        *,
        operation: Operation,
        source: Source,
        canonical: str | None = None,
        may_have_taken_effect: bool = False,
        reconcile_by: ReconcileKey | None = None,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            may_have_taken_effect=may_have_taken_effect,
            reconcile_by=reconcile_by,
        )
        self.source = source
        self.canonical = canonical


class PrestoPayResponseError(PrestoPayError):
    source: Source
    raw_body: str | None

    def __init__(
        self,
        message: str,
        *,
        operation: Operation,
        source: Source,
        raw_body: str | None = None,
        may_have_taken_effect: bool = False,
        reconcile_by: ReconcileKey | None = None,
    ) -> None:
        super().__init__(
            message,
            operation=operation,
            may_have_taken_effect=may_have_taken_effect,
            reconcile_by=reconcile_by,
        )
        self.source = source
        self.raw_body = raw_body


def may_have_succeeded(exc: BaseException) -> bool:
    return isinstance(exc, PrestoPayError) and exc.may_have_taken_effect
