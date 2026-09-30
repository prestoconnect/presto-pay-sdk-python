from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

# A fixed offset rather than ZoneInfo("Asia/Kuala_Lumpur"): the gateway specifies +08:00, and a named zone
# would tie every signature to whatever that zone's rules become.
TZ8 = timezone(timedelta(hours=8))

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MILLISECOND = timedelta(milliseconds=1)
_GATEWAY_TIMESTAMP = re.compile(r"[0-9]{14}\.[0-9]{3}")


def format_gateway_timestamp(moment: datetime) -> str:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("format_gateway_timestamp needs an aware datetime; attach a tzinfo")
    local = moment.astimezone(TZ8)
    return f"{local:%Y%m%d%H%M%S}.{local.microsecond // 1000:03d}"


def format_epoch_millis(epoch_millis: int) -> str:
    return format_gateway_timestamp(_EPOCH + timedelta(milliseconds=epoch_millis))


def format_epoch_seconds(epoch_seconds: float) -> str:
    return format_epoch_millis(round(epoch_seconds * 1000))


def parse_gateway_timestamp(ts: str) -> datetime:
    if not isinstance(ts, str) or _GATEWAY_TIMESTAMP.fullmatch(ts) is None:
        raise ValueError(f"{ts!r} is not a gateway timestamp (yyyyMMddHHmmss.SSS)")
    try:
        return datetime(
            int(ts[0:4]),
            int(ts[4:6]),
            int(ts[6:8]),
            int(ts[8:10]),
            int(ts[10:12]),
            int(ts[12:14]),
            int(ts[15:18]) * 1000,
            tzinfo=TZ8,
        )
    except ValueError as exc:
        raise ValueError(f"{ts!r} is not a calendar date and time") from exc


def to_epoch_millis(moment: datetime) -> int:
    return (moment - _EPOCH) // _ONE_MILLISECOND


def to_epoch_seconds(moment: datetime) -> float:
    return (moment - _EPOCH).total_seconds()
