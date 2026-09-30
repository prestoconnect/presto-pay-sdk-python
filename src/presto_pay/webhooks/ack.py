from __future__ import annotations

from typing import Final

from presto_pay.errors import PrestoPayResponseError, PrestoPaySignatureError


class NotifyAck:
    OK: Final = b'{"resend":false}'
    RESEND: Final = b'{"resend":true}'
    CONTENT_TYPE: Final = "application/json"

    @staticmethod
    def for_error(exc: BaseException) -> bytes:
        # A webhook that fails verification (bad signature, foreign mid, stale ts, malformed body) fails the same
        # way on every redelivery, so asking Presto to resend only builds a loop. The same exception types raised
        # by an outbound call inside the handler are the merchant's own failure, and the event must come again.
        if isinstance(exc, PrestoPaySignatureError | PrestoPayResponseError) and exc.source == "webhook":
            return NotifyAck.OK
        return NotifyAck.RESEND
