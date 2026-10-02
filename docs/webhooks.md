# Webhook handling

Presto POSTs a signed JSON body to the `notify_url` you gave on `init`, `reverse` or `refund`. The handler
answers HTTP 401 if the signature is bad, and otherwise HTTP 200 with `NotifyAck.OK` (`{"resend":false}`) or
`NotifyAck.RESEND` (`{"resend":true}`). The [quick start](../README.md#4-handle-the-webhook) has a complete
Flask handler; this guide explains each part, with Django, Flask and FastAPI handlers at the end.

## Verify the raw body

The signature covers the exact bytes Presto sent. If a framework parses the body into a dict and you
re-serialize it, those bytes are lost, so `verify()` refuses a dict. Pass the body as bytes or str:

| Framework | Raw body |
|-----------|----------|
| Django | `request.body` |
| Flask | `request.get_data()` |
| FastAPI / Starlette | `await request.body()` |
| Pyramid | `request.body` |
| aiohttp | `await request.read()` |

`verify()` checks, in order:

1. The signature.
2. The required fields.
3. That `mid` is one of your merchant IDs. One Presto key signs webhooks for every merchant, so a valid
   signature alone doesn't mean the event is yours.
4. That `ts` is within 15 minutes of your clock, in either direction.

`verify()` is synchronous even on `AsyncPrestoPay`, because it does no I/O.

A service that only receives webhooks needs Presto's certificate and your merchant IDs, but not the private key:

```python
from presto_pay import create_webhook_verifier

verifier = create_webhook_verifier(
    merchant_id={"PW2401XH9KCX", "PW2401OTHER"},  # one endpoint can serve several mids
    presto_public_key=Path("presto.der"),
)
```

## Guard on the order, not the event

Presto retries a delivery 1, 2, 5 and 10 minutes after the first attempt, which makes up to five deliveries over
about 18 minutes, and your return page may update the same order first. A handler that fulfils on every
delivery can fulfil the same order five times.

Check the order record instead of the event. Apply the queried status in one conditional update, so only one
caller can finalise the order, and fulfil only when that update moved the order into `Authorised`:

```sql
UPDATE orders SET status = %s WHERE txn_ref_num = %s AND status = 'PendingAuthorise'
```

Once an order is finalised, apply only the statuses that can follow payment (`PendingRefund`,
`PartialRefunded`, `Refunded`, `PendingReverse`, `Reversed`), never fulfil again, and never let an older status
overwrite `Refunded` or `Reversed`. Create the fulfilment job in the same transaction as the update, so a crash
rolls both back and the redelivery can try again. A redelivery, a replay, or a webhook that arrives after the
return page then finds the order already in that status and does nothing.

The handlers below call an `apply_payment_status` function like this Django one; the Flask and FastAPI versions
issue the same two updates:

```python
from django.db import transaction
from presto_pay import PaymentStatus

from .models import FulfilmentJob, Order

PAID_AND_STILL_OPEN = [
    PaymentStatus.AUTHORISED,
    PaymentStatus.PENDING_REVERSE,
    PaymentStatus.PENDING_REFUND,
    PaymentStatus.PARTIAL_REFUNDED,
]
AFTER_PAYMENT = [*PAID_AND_STILL_OPEN, PaymentStatus.REVERSED, PaymentStatus.REFUNDED]


def apply_payment_status(txn_ref_num: str, status: str) -> None:
    with transaction.atomic():
        orders = Order.objects.filter(txn_ref_num=txn_ref_num)
        finalised = orders.filter(status=PaymentStatus.PENDING_AUTHORISE).update(status=status)
        if finalised and status == PaymentStatus.AUTHORISED:
            FulfilmentJob.objects.create(txn_ref_num=txn_ref_num)
        elif not finalised and status in AFTER_PAYMENT:
            orders.filter(status__in=PAID_AND_STILL_OPEN).exclude(status=status).update(status=status)
```

## Choosing the reply

Answer a `PrestoPaySignatureError` from `verify()` (a bad signature, a foreign `mid` or a stale `ts`) with
HTTP 401 and no body. For anything else, `NotifyAck.for_error(exc)` picks the reply:

- A `PrestoPayResponseError` raised by `verify()` (its `source` is `"webhook"`), meaning a malformed body
  → `OK`. A malformed body fails the same way on every redelivery, so asking for a resend only builds a loop.
  `for_error` also answers `OK` for a webhook signature error, if you haven't answered 401 first.
- Anything else → `RESEND`. This covers your own transient failures, such as the database being down. It also
  covers SDK errors from calls your fulfilment code makes: a `query` that fails inside the handler has
  `source="response"`, so the event is redelivered rather than lost.

## Getting the payment status

A webhook tells you that something happened to a payment. It doesn't tell you the payment's status. The event
carries `event_code` (`Authorised`, `Refunded`, `Reversed`, `Cancelled`, `Expired` or a newer code) and
`success`, exactly as Presto sent them. The SDK doesn't derive a status from those two fields.

To get the status, call `query` in the handler:

```python
event = presto.webhooks.verify(body)
payment = presto.payments.query(presto_mrn=event.presto_mrn, payment_ref_num=event.payment_ref_num)
payment.payment_status  # e.g. "Authorised", "PartialRefunded", "Refunded"
```

`query` always returns the payment's latest status, whatever order webhooks and the payer's redirect arrive in.
It also covers cases that the event code alone can't settle, such as a failed refund leaving the payment in its
previous state.

If the `query` fails, `NotifyAck.for_error` answers `{"resend":true}`, and Presto redelivers the event so you can
try again.

## Django

```python
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from presto_pay import NotifyAck, PrestoPaySignatureError

from .orders import apply_payment_status
from .payments import presto


@csrf_exempt
@require_POST
def presto_notify(request):
    try:
        event = presto.webhooks.verify(request.body)
    except PrestoPaySignatureError:
        return HttpResponse(status=401)
    except Exception as exc:
        return HttpResponse(NotifyAck.for_error(exc), content_type=NotifyAck.CONTENT_TYPE)

    try:
        payment = presto.payments.query(presto_mrn=event.presto_mrn, payment_ref_num=event.payment_ref_num)
        apply_payment_status(event.txn_ref_num, payment.payment_status)
        body = NotifyAck.OK
    except Exception as exc:
        body = NotifyAck.for_error(exc)
    return HttpResponse(body, content_type=NotifyAck.CONTENT_TYPE)
```

## Flask

```python
from flask import Flask, request
from presto_pay import NotifyAck, PrestoPaySignatureError

app = Flask(__name__)


@app.post("/presto/notify")
def presto_notify():
    try:
        event = presto.webhooks.verify(request.get_data())
    except PrestoPaySignatureError:
        return "", 401
    except Exception as exc:
        return NotifyAck.for_error(exc), 200, {"Content-Type": NotifyAck.CONTENT_TYPE}

    try:
        payment = presto.payments.query(presto_mrn=event.presto_mrn, payment_ref_num=event.payment_ref_num)
        apply_payment_status(db.session, event.txn_ref_num, payment.payment_status)
        db.session.commit()
        body = NotifyAck.OK
    except Exception as exc:
        db.session.rollback()
        body = NotifyAck.for_error(exc)
    return body, 200, {"Content-Type": NotifyAck.CONTENT_TYPE}
```

## FastAPI

```python
import asyncpg
from fastapi import FastAPI, Request, Response
from presto_pay import AsyncPrestoPay, NotifyAck, PaymentStatus, PrestoPaySignatureError

app = FastAPI()
presto: AsyncPrestoPay = ...
pool: asyncpg.Pool = ...


@app.post("/presto/notify")
async def presto_notify(request: Request) -> Response:
    try:
        event = presto.webhooks.verify(await request.body())
    except PrestoPaySignatureError:
        return Response(status_code=401)
    except Exception as exc:
        return Response(NotifyAck.for_error(exc), media_type=NotifyAck.CONTENT_TYPE)

    try:
        payment = await presto.payments.query(presto_mrn=event.presto_mrn, payment_ref_num=event.payment_ref_num)
        async with pool.acquire() as connection, connection.transaction():
            finalised = await connection.fetchval(
                "UPDATE orders SET status = $1 WHERE txn_ref_num = $2 AND status = 'PendingAuthorise' "
                "RETURNING txn_ref_num",
                payment.payment_status,
                event.txn_ref_num,
            )
            if finalised is not None and payment.payment_status == PaymentStatus.AUTHORISED:
                await enqueue_fulfilment(connection, event.txn_ref_num)
            elif finalised is None:
                await apply_status_after_payment(connection, event.txn_ref_num, payment.payment_status)
        body = NotifyAck.OK
    except Exception as exc:
        body = NotifyAck.for_error(exc)
    return Response(body, media_type=NotifyAck.CONTENT_TYPE)
```

## Clock and window

The 15-minute window matches the gateway's own request window. If your host queues notifications before
verifying them, you can widen it with `WebhookOptions(max_timestamp_age=...)` on the client, or
`max_timestamp_age=` on `create_webhook_verifier`. `None` disables the check. Widen or disable it only if your
order update is guarded as in [Guard on the order, not the event](#guard-on-the-order-not-the-event).
