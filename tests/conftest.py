from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SPEC = Path(__file__).resolve().parent.parent / "spec"
KEYS = SPEC / "keys"
VECTORS = SPEC / "vectors"

TEST_PRIVATE_KEY = KEYS / "test-merchant-key.pem"
TEST_PUBLIC_KEY = KEYS / "test-merchant-public.pem"
TEST_CERT_PEM = KEYS / "test-merchant-cert.pem"
TEST_CERT_DER = KEYS / "test-merchant-cert.der"
PRESTO_STAGING_CERT = KEYS / "presto-staging.der"


def load_vectors(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((VECTORS / name).read_text(encoding="utf-8"))
    return loaded
