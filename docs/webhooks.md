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

## Deduplicate on `event_ref_num`

Presto retries a delivery 1, 2, 5 and 10 minutes after the first attempt, which makes up to five deliveries over
about 18 minutes. Each redelivery carries a fresh `ts`, so it always passes the freshness check. `event_ref_num`
stays the same across redeliveries, which makes it the deduplication key. A handler that fulfils on every
delivery can fulfil the same order five times.

Make the deduplication atomic with the fulfilment: insert `event_ref_num` into a table with a unique constraint,
in the same transaction as the fulfilment. Then a duplicate is a no-op, and a crash rolls both back so the
redelivery can try again.

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
try again. Record `event_ref_num` only after you have processed the event, so a redelivery isn't mistaken for a
duplicate.

## Django

```python
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from presto_pay import NotifyAck, PrestoPaySignatureError

from .models import PrestoWebhookEvent  # event_ref_num = models.CharField(max_length=64, unique=True)
from .payments import presto, fulfil


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
        try:
            with transaction.atomic():
                PrestoWebhookEvent.objects.create(event_ref_num=event.event_ref_num)
                fulfil(event, payment.payment_status)
        except IntegrityError:
            pass
        body = NotifyAck.OK
    except Exception as exc:
        body = NotifyAck.for_error(exc)
    return HttpResponse(body, content_type=NotifyAck.CONTENT_TYPE)
```

## Flask

```python
from flask import Flask, request
from presto_pay import NotifyAck, PrestoPaySignatureError
from sqlalchemy.exc import IntegrityError

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
        try:
            db.session.add(WebhookEvent(event_ref_num=event.event_ref_num))  # unique column
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
        else:
            fulfil(event, payment.payment_status)
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
from presto_pay import AsyncPrestoPay, NotifyAck, PrestoPaySignatureError

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
            inserted = await connection.fetchval(
                "INSERT INTO presto_webhook_events (event_ref_num) VALUES ($1) "
                "ON CONFLICT DO NOTHING RETURNING event_ref_num",
                event.event_ref_num,
            )
            if inserted is not None:
                await fulfil(connection, event, payment.payment_status)
        body = NotifyAck.OK
    except Exception as exc:
        body = NotifyAck.for_error(exc)
    return Response(body, media_type=NotifyAck.CONTENT_TYPE)
```

## Clock and window

The 15-minute window matches the gateway's own request window. If your host queues notifications before
verifying them, you can widen it with `WebhookOptions(max_timestamp_age=...)` on the client, or
`max_timestamp_age=` on `create_webhook_verifier`. `None` disables the check. Widen or disable it only if you
deduplicate on `event_ref_num`.
