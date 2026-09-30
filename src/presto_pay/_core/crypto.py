from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence

from presto_pay._core.keys import PrestoPublicKey, PrivateKey


def sign(private_key: PrivateKey, canonical: str) -> str:
    return base64.b64encode(private_key.sign(canonical.encode("utf-8"))).decode("ascii")


def verify(public_keys: Sequence[PrestoPublicKey], canonical: str, signature: object) -> bool:
    if not isinstance(signature, str) or not signature:
        return False
    try:
        raw = base64.b64decode(signature, validate=True)
        data = canonical.encode("utf-8")
    except (binascii.Error, ValueError):
        return False
    return any(key.verify(raw, data) for key in public_keys)
