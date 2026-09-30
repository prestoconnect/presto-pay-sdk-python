# Presto Pay SDK for Python

[![CI](https://github.com/prestoconnect/presto-pay-sdk-python/actions/workflows/ci.yml/badge.svg)](https://github.com/prestoconnect/presto-pay-sdk-python/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/LICENSE)

A Python 3.11+ library for the **Presto Connect** payment gateway. It takes care of the parts of a signed
payment API that are easy to get slightly wrong by hand: RSA request signing, verifying response and webhook
signatures, gateway timestamps, loading keys (including the onboarding `.p12` keystore), and errors that tell
you when a payment might have gone through anyway.

- **Sync and async** with the same API: `PrestoPay` for Django, Flask and Celery, and `AsyncPrestoPay` for
  FastAPI and other asyncio apps. Both run on the same core, and CI checks that they send identical bytes.
- Two dependencies: `cryptography` and `httpx`. No pydantic.
- Fully typed (`py.typed`, `mypy --strict`). Results are frozen dataclasses with snake_case fields.

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Merchant identity](#merchant-identity)
- [Configuration from environment](#configuration-from-environment)
- [Retries and idempotency](#retries-and-idempotency)
- [Webhooks](#webhooks)
- [Errors](#errors)
- [Custom HTTP client](#custom-http-client)
- [Debugging signatures](#debugging-signatures)
- [Samples](#samples)
- [Contributing](#contributing)
- [License](#license)

## Install

```bash
pip install presto-pay-sdk
```

The package imports as `presto_pay`. CI runs it on CPython 3.11, 3.12, 3.13 and 3.14.

## Quick start

```python
from pathlib import Path

from presto_pay import PaymentMethod, PrestoPay, TxnType

presto = PrestoPay(
    environment="staging",  # "staging", "production", or Environment(base_url=...)
    merchant_id="YOUR_MID",  # mid, sent on every request
    private_key=Path("partner.p12"),  # onboarding keystore, PKCS#8 PEM, or DER
    private_key_password="keystore-password",
    presto_public_key=Path("presto.der"),  # Presto's certificate (PEM or DER), or a list during rotation
)

payment = presto.payments.init(
    presto_mrn="YOUR_PRESTO_MRN",  # required on every request
    txn_type=TxnType.WEB_PAY,
    txn_ref_num="order-123",
    display_desc="Order 123",
    amount=10_000,  # minor currency units: MYR 100.00
    currency_code="MYR",
    notify_url="https://your-app.example/presto/notify",
    redirect_url="https://your-app.example/presto/return/order-123",
    allowed_payment_methods=[PaymentMethod.WALLET],
)
redirect(payment.payment_url)
```

The async client has the same API, but you `await` each call:

```python
from presto_pay import AsyncPrestoPay

async with AsyncPrestoPay(environment="staging", ...) as presto:
    payment = await presto.payments.init(...)
```

Key material is parsed when the client is constructed, so a bad key or password fails at startup rather than
on the first payment. Give each order its own `txn_ref_num`. See [payments and errors](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/payments-and-errors.md)
for `query`, `reverse` and `refund`.

## Merchant identity

Each client belongs to one merchant. `merchant_id` (`mid`) goes on the constructor and is sent with every
request. The client's webhook verifier rejects events addressed to any other `mid`. `presto_mrn` is passed on
each call, because one `mid` can have several.

To serve several merchants, create one client per `mid`. They can share keys and an `httpx` client. To receive
webhooks for several merchants on one endpoint, use `create_webhook_verifier(merchant_id={...})`.

## Configuration from environment

```python
import os

from presto_pay import PrestoPay

presto = PrestoPay.from_env(os.environ)
```

`from_env` accepts any mapping: `os.environ`, a dict from a secrets manager, or flattened Django settings. It
also takes the constructor's other options as keyword arguments, such as `http_client`, `deadline` and
`strict`. `AsyncPrestoPay.from_env` works the same way.

| Variable | Description |
|----------|-------------|
| `PRESTOPAY_ENV` or `PRESTOPAY_BASE_URL` | `staging` / `production`, or an explicit HTTPS base URL (set one, not both) |
| `PRESTOPAY_MID` | Merchant ID |
| `PRESTOPAY_PRIVATE_KEY` or `PRESTOPAY_PRIVATE_KEY_FILE` | PEM text, or a path to a PEM, DER or `.p12` file |
| `PRESTOPAY_PRIVATE_KEY_PASSWORD` | Keystore or encrypted-PEM password, if any |
| `PRESTOPAY_PUBLIC_KEY` or `PRESTOPAY_PUBLIC_KEY_FILE` | Presto's certificate (PEM or DER) or SPKI public key |

If a PEM is stored on one line with literal `\n` sequences (common in `.env` files and secrets managers), it is
unescaped automatically.

### The onboarding `.p12`

`cryptography` reads Presto's PKCS#12 keystore directly, including its RC2-40 certificate bag, which the OpenSSL 3
command line rejects unless the legacy provider is loaded. You don't need to convert it; pass the file and its
password.

## Retries and idempotency

The SDK **never** automatically resends `init`, `reverse` or `refund` once any byte of the request may have
reached the gateway. It retries them only when `httpx` shows the request was never sent (DNS failure, refused or
timed-out connect, TLS failure, pool timeout). `query` is read-only, so it is also retried on other transport
errors and on HTTP 5xx.

Retries use exponential backoff with full jitter and honour `Retry-After`. All attempts, backoff included,
share one whole-call `deadline` (30 s by default). Configure them with `retry_reads=RetryReads(max_retries=2,
initial_backoff=0.2, max_backoff=5.0)`.

`AsyncPrestoPay` enforces the deadline exactly. `PrestoPay` limits each connect, write and read to the time
remaining, and checks the deadline after each chunk of the response. A single network operation that stalls
can still run up to its own limit before the deadline is noticed.

When the outcome is unknown, the error says so, and it carries the lookup key you need to find out:

```python
from presto_pay import PrestoPayError

try:
    payment = presto.payments.init(...)
except PrestoPayError as exc:
    if not exc.may_have_taken_effect or exc.reconcile_by is None:
        raise
    payment = presto.payments.query(**exc.reconcile_by)
```

`may_have_taken_effect` is set where the error is raised, because the answer depends on the operation. For
example, an HTTP 502 on `init` is ambiguous, but an HTTP 502 on `query` means nothing happened. `reconcile_by`
holds `presto_mrn` plus `txn_ref_num` after `init`, or `payment_ref_num` after `reverse` and `refund`. It is
`None` after `presto.raw.post`, which can't know the lookup key for an endpoint the SDK doesn't model.

`init` is idempotent by `txn_ref_num` on the gateway side. Resending an existing `txn_ref_num` returns that
payment's current status instead of creating a second one. Business error `1203` proves a record exists but not
what state it is in, so it is also flagged `may_have_taken_effect`.

## Webhooks

Presto POSTs a signed JSON body to your `notify_url`, which must be publicly reachable. Always verify the
**raw** request body. The verifier checks four things: the signature, the required fields, that the `mid`
belongs to you, and that `ts` is within 15 minutes of your clock. Then deduplicate on `event_ref_num` before
fulfilling:

```python
from presto_pay import NotifyAck


@app.post("/presto/notify")  # Flask
def presto_notify():
    try:
        event = presto.webhooks.verify(request.get_data())
        record_once(event.event_ref_num, event)  # unique constraint on event_ref_num
        body = NotifyAck.OK
    except Exception as exc:
        body = NotifyAck.for_error(exc)
    return body, 200, {"Content-Type": NotifyAck.CONTENT_TYPE}
```

`NotifyAck.for_error` replies `{"resend":false}` only when verifying the webhook itself failed: a bad
signature, a foreign `mid`, a stale `ts`, or a malformed body. Presto retries at 1, 2, 5 and 10 minutes, and each
of those redeliveries would fail the same way. Anything else gets `{"resend":true}`. That includes your own
transient failures, and SDK errors from calls your handler makes, such as a `query` that fails.

A process that only receives webhooks doesn't need the private key:

```python
from presto_pay import create_webhook_verifier

verifier = create_webhook_verifier(merchant_id=os.environ["PRESTOPAY_MID"], presto_public_key=Path("presto.der"))
```

For Django, FastAPI and Flask handlers, deduplication and the raw-body accessor for each framework, see
[webhook handling](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/webhooks.md).

## Errors

Every error is a `PrestoPayError` and carries `operation`, `may_have_taken_effect` and `reconcile_by`.

| Class | When | Extra attributes |
|-------|------|------------------|
| `PrestoPayConfigError` | Invalid options or request input, including bad keys and unencodable strings | `field` |
| `PrestoPayTransportError` | Network failure or timeout | `request_not_sent` |
| `PrestoPayApiError` | Non-200 status (`kind="http"`) or `success: false` (`kind="business"`) | `http_status`, `error_code`, `error_message`, `raw_body`; `canonical` on `1006`/`1007`; `clock_offset` on `1005` |
| `PrestoPaySignatureError` | Missing or invalid signature, wrong webhook `mid`, stale webhook `ts` | `source`, `canonical` |
| `PrestoPayResponseError` | Malformed body, missing required field, bad `ts`, echo mismatch | `source`, `raw_body` |

Compare error codes against `ErrorCode`, for example `ErrorCode.CLOCK_SKEW == "1005"`. The original `httpx`
exception is chained as `__cause__`. No `httpx` type is part of the public API.

**Redaction.** `raw_body` and `canonical` can contain card, receipt and customer details. By default the
values of `cardBin`, `cardSummary`, `receiptEmail`, `receiptName`, `qrValue`, `payerRefNum`, `bindData`,
`deviceIp`, `deviceRefNum` and `transactionalData` are replaced with `[redacted]`, including inside the
stringified `paymentDetails`. An unparseable body is replaced entirely. `str()` and `repr()` of an error never
include a body. To keep full bodies for debugging, pass `redact_error_bodies=False`.

**Strict mode.** `strict=True` rejects contract drift that is tolerated by default: a number where the gateway
documents a string, or a field longer than its documented maximum. Use it in staging.

## Custom HTTP client

Pass your own `httpx.Client` (or `httpx.AsyncClient`) to set up proxies, TLS, connection limits or tracing, or to
share a pool:

```python
import httpx

presto = PrestoPay(..., http_client=httpx.Client(proxy="http://proxy.internal:3128"))
```

The SDK sets the timeout on each request and turns redirects off. It never closes a client you pass in. It
closes only the one it creates, when you use `with` / `async with`, `close()` or `aclose()`. Don't configure the
client to retry requests. `httpx.HTTPTransport(retries=n)` is safe because it retries only failed connections,
which never send any bytes.

## Debugging signatures

`canonicalize(body)` builds the canonical string for a raw JSON body, which is the exact text that gets signed.
When the gateway rejects a request signature (`1006`/`1007`), `exc.canonical` holds the string the SDK signed.
For endpoints the SDK doesn't wrap yet, `presto.raw.post(path, body)` signs, sends, verifies and returns the
parsed dict. `presto.raw.sign(canonical)` and `presto.raw.verify_body(body)` expose the two halves.

`parse_gateway_timestamp` reads the gateway's `yyyyMMddHHmmss.SSS` date fields into aware `datetime`s at
UTC+08:00. Result date fields are left as strings.

## Samples

[`sample/`](https://github.com/prestoconnect/presto-pay-sdk-python/tree/main/sample) is a runnable **MyStore** checkout against Presto staging. It includes the hosted and
self-hosted payment-method flows, a return page that queries the payment's status, and a webhook handler with a
"recent webhooks" list. It comes as two self-contained projects:

- [`sample/flask-store/`](https://github.com/prestoconnect/presto-pay-sdk-python/tree/main/sample/flask-store): Flask on the sync `PrestoPay` client.
- [`sample/fastapi-store/`](https://github.com/prestoconnect/presto-pay-sdk-python/tree/main/sample/fastapi-store): FastAPI on the async `AsyncPrestoPay` client.

See [sample/README.md](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/sample/README.md).

## Contributing

[CONTRIBUTING.md](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/CONTRIBUTING.md) covers building, testing, code style and releasing. Report security issues
as described in [SECURITY.md](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/SECURITY.md), not in a public issue.

`spec/` is a checked-in copy of the shared wire contract and test vectors. The commit it was copied from is
recorded in [`spec/.source-commit`](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/spec/.source-commit). Real merchant or staging credentials must never be
committed to this repository.

## License

Apache License 2.0. See [LICENSE](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/LICENSE).
