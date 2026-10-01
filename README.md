# Presto Pay SDK for Python

[![PyPI](https://img.shields.io/pypi/v/presto-pay-sdk.svg)](https://pypi.org/project/presto-pay-sdk/)
[![CI](https://github.com/prestoconnect/presto-pay-sdk-python/actions/workflows/ci.yml/badge.svg)](https://github.com/prestoconnect/presto-pay-sdk-python/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/LICENSE)

Accept payments through the **Presto Connect** payment gateway from any Python application. The SDK signs every
request, verifies every response and webhook, and gives you typed requests and results, so you don't have to
handle the gateway's signature scheme yourself.

- **Python 3.11+**, sync and async with the same API: `PrestoPay` for Django, Flask and Celery, and
  `AsyncPrestoPay` for FastAPI and other asyncio apps
- Two dependencies: `cryptography` and `httpx`
- Fully typed: results are frozen dataclasses with snake_case fields

## Contents

- [Install](#install)
- [Before you start](#before-you-start)
- [How a payment works](#how-a-payment-works)
- [Quick start](#quick-start)
- [Payment statuses](#payment-statuses)
- [Next steps](#next-steps)

## Install

```bash
pip install presto-pay-sdk
```

The package imports as `presto_pay`.

## Before you start

### 1. Create your key pair

You sign every request with your own RSA private key, and Presto verifies it with the matching public key.
Generate the pair yourself with `openssl`; the private key never leaves your systems:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out merchant-key.pem
openssl req -new -x509 -key merchant-key.pem -days 99999 -subj "/CN=Your Company" -outform DER -out merchant.der
```

`merchant-key.pem` is your private key; keep it secret and out of source control. The SDK also reads a `.p12`
keystore or an encrypted PEM if that's what you have. Send `merchant.der` (your public key, in the DER format
Presto requires) to Presto.
The certificate is valid for 99999 days (until the year 2300), so you won't have to generate a new key pair
and register it with Presto again.

### 2. Get your details from Presto

| From Presto | What it is | Where it goes |
|-------------|------------|---------------|
| Merchant ID (`mid`) | Identifies your merchant account | `PrestoPay(merchant_id=...)` |
| Presto merchant reference (`prestoMrn`) | Identifies the shop or outlet; one `mid` can have several | Every request: `presto_mrn=...` |
| Presto certificate (`.der`) | Verifies Presto's responses and webhooks; the SDK reads it as is | `PrestoPay(presto_public_key=...)` |

Staging and production are separate: each has its own `mid`, `prestoMrn` and Presto certificate, and you
register your public key for each. Never mix them.

## How a payment works

```
 Your server                      Presto                     Shopper's browser
     |---- 1. init ------------------>|                              |
     |<--- payment_url ---------------|                              |
     |---- 2. redirect to payment_url ------------------------------>|
     |                                |<---- 3. shopper pays --------|
     |                                |---- 4a. redirect to your redirect_url -->|
     |<--- 4b. webhook to your notify_url                            |
     |---- 5. query ----------------->|                              |
```

1. Your server calls `init` with your order's reference and amount. Presto returns a `payment_url`.
2. You redirect the shopper to `payment_url`.
3. The shopper chooses a payment method and pays on Presto's page.
4. Presto sends the shopper's browser back to your `redirect_url` **and** POSTs a signed webhook to your
   `notify_url`. These happen independently and can arrive in either order.
5. On both, you call `query` to get the payment's status from Presto, and update the order.

The identifiers you'll see:

| Name | Who creates it | What it's for |
|------|----------------|---------------|
| `txn_ref_num` | You | Your reference for the payment, such as an order ID. Unique per payment, at most 50 characters |
| `payment_ref_num` | Presto | Presto's reference for the payment, returned by `init` |
| `event_ref_num` | Presto | Identifies one webhook event; stays the same when Presto redelivers it |
| `reversal_ref_num`, `refund_ref_num` | You | Your reference for a reversal or a refund |

## Quick start

These examples use Flask and the sync `PrestoPay`. With `AsyncPrestoPay` the code is the same, but you `await`
each payment call. For Django and FastAPI, see
[Webhooks](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/webhooks.md#django).

### 1. Create the client

Create it once at startup and reuse it. Bad keys or a wrong password fail here, not on the first payment.

```python
from pathlib import Path

from presto_pay import PrestoPay

presto = PrestoPay(
    environment="staging",
    merchant_id="YOUR_MID",
    private_key=Path("merchant-key.pem"),
    presto_public_key=Path("presto.der"),
)
```

To configure the client from environment variables instead, see
[Configuration](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/production.md#configuration-from-environment).

### 2. Start a payment

```python
from flask import redirect

from presto_pay import PaymentMethod, TxnType

payment = presto.payments.init(
    presto_mrn="YOUR_PRESTO_MRN",
    txn_type=TxnType.WEB_PAY,
    txn_ref_num=order_id,
    display_desc=f"Order {order_id}",
    amount=10_000,  # minor units: MYR 100.00
    currency_code="MYR",
    notify_url="https://your-app.example/presto/notify",
    redirect_url=f"https://your-app.example/presto/return/{order_id}",
    allowed_payment_methods=[PaymentMethod.PM_PG_CARD],  # Skip this unless you build your own payment selection page
)

# Save payment.payment_ref_num with the order, then send the shopper to Presto.
if payment.payment_url is None:
    raise RuntimeError(f"Presto returned no payment_url for {order_id}")
return redirect(payment.payment_url)
```

`notify_url` must be reachable from the internet; on your own machine, use a tunnel such as ngrok.

### 3. Show the result on your return page

The redirect only tells you the shopper came back, not whether they paid. Ask Presto:

```python
from presto_pay import PaymentStatus

result = presto.payments.query(presto_mrn="YOUR_PRESTO_MRN", txn_ref_num=order_id)

if result.payment_status == PaymentStatus.AUTHORISED:
    ...  # Paid: show the confirmation.
elif result.payment_status == PaymentStatus.PENDING_AUTHORISE:
    ...  # Not finished yet: show "processing" and check again shortly.
else:
    ...  # Not paid (Failed, Cancelled, Expired, ...).
```

### 4. Handle the webhook

A webhook tells you something happened to a payment (`event_code`, and `success` for whether it worked), not
the payment's resulting status, so query for that here too. Verify the **raw** request body, exactly as
received.

```python
from flask import request

from presto_pay import NotifyAck, PrestoPaySignatureError


@app.post("/presto/notify")
def presto_notify():
    try:
        event = presto.webhooks.verify(request.get_data())
    except PrestoPaySignatureError:
        return "", 401  # forged, for another mid, or too old
    except Exception as exc:
        return NotifyAck.for_error(exc), 200, {"Content-Type": NotifyAck.CONTENT_TYPE}  # malformed body

    if not orders.is_event_handled(event.event_ref_num):
        try:
            payment = presto.payments.query(presto_mrn=event.presto_mrn, payment_ref_num=event.payment_ref_num)
            orders.update_status(event.txn_ref_num, payment.payment_status, event.event_ref_num)
        except Exception:
            return NotifyAck.RESEND, 200, {"Content-Type": NotifyAck.CONTENT_TYPE}
    return NotifyAck.OK, 200, {"Content-Type": NotifyAck.CONTENT_TYPE}
```

`NotifyAck.OK` tells Presto the event is handled. `NotifyAck.RESEND` asks Presto to deliver it again (after 1,
2, 5 and 10 minutes), which you want when your own processing failed. Presto redelivers an event with the same
`event_ref_num`, so record it once handled and skip it on later deliveries. See
[Webhooks](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/webhooks.md) for the details.

Update the order the same way from your return page and your webhook: whichever arrives first records the
status, and the other finds it already done.

## Payment statuses

`payment_status` is one of these strings; compare it with the `PaymentStatus` constants.

| Status | Meaning | What to do |
|--------|---------|------------|
| `PendingAuthorise` | Created; the shopper hasn't finished paying | Wait. It becomes `Expired` if not paid within 15 minutes of `init` |
| `Authorised` | Paid | Fulfil the order |
| `Failed` | The payment attempt failed | Don't fulfil |
| `Cancelled` | Cancelled before it was paid, for example by `reverse` | Don't fulfil |
| `Expired` | Not paid within 15 minutes | Don't fulfil; start a new payment if the shopper returns |
| `PendingReverse` | A reversal is in progress | Query again later |
| `Reversed` | The payment was reversed | Treat the order as cancelled |
| `PendingRefund` | A refund is in progress | Query again later |
| `PartialRefunded` | Part of the amount was refunded | Update the order's refunded amount |
| `Refunded` | The full amount was refunded | Treat the order as refunded |

The gateway can add statuses, so handle an unknown value without failing.

## Next steps

- [Payments and errors](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/payments-and-errors.md):
  look up, reverse and refund payments; handle errors, timeouts and retries safely.
- [Webhooks](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/webhooks.md): raw bodies,
  replies, redelivery, deduplication, and complete Django, Flask and FastAPI handlers.
- [Production](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/docs/production.md):
  configuration, keys, several merchants, custom HTTP clients, the go-live checklist and troubleshooting.
- [Samples](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/sample/README.md): a runnable
  checkout against Presto staging, on Flask with `PrestoPay`
  ([`flask-store`](https://github.com/prestoconnect/presto-pay-sdk-python/tree/main/sample/flask-store)) and on
  FastAPI with `AsyncPrestoPay`
  ([`fastapi-store`](https://github.com/prestoconnect/presto-pay-sdk-python/tree/main/sample/fastapi-store)).

## Contributing

[CONTRIBUTING.md](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/CONTRIBUTING.md) covers
building, testing, code style and releasing. Report security issues as described in
[SECURITY.md](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/SECURITY.md), not in a public
issue. Real merchant or staging credentials never belong in this repository.

## License

Apache License 2.0. See [LICENSE](https://github.com/prestoconnect/presto-pay-sdk-python/blob/main/LICENSE).
