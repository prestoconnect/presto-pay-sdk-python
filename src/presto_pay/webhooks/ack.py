from __future__ import annotations

from typing import Final

from presto_pay.errors import PrestoPayResponseError, PrestoPaySignatureError


class NotifyAck:
    OK: Final = b'{"resend":false}'
    RESEND: Final = b'{"resend":true}'
    CONTENT_TYPE: Final = "application/json"

    @staticmethod
    def for_error(exc: BaseException) -> bytes:
        # A bad signature, a foreign mid, a stale ts or a malformed body fails the same way on every
        # redelivery, so asking Presto to resend only builds a loop. Resend is for the merchant's own
        # transient failures.
        if isinstance(exc, PrestoPaySignatureError | PrestoPayResponseError):
            return NotifyAck.OK
        return NotifyAck.RESEND
