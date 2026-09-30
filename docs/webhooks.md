# Webhook handling

Presto POSTs a signed JSON body to the `notify_url` you gave on `init`, `reverse` or `refund`. The handler must
answer HTTP 200 with `NotifyAck.OK` (`{"resend":false}`) or `NotifyAck.RESEND` (`{"resend":true}`).

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

`NotifyAck.for_error(exc)` picks the reply for a caught exception:

- `PrestoPaySignatureError` and `PrestoPayResponseError` → `OK`. A bad signature, a foreign `mid`, a stale `ts`
  or a malformed body fails the same way on every redelivery, so asking for a resend only builds a loop.
- Anything else → `RESEND`. This covers your own transient failures, such as the database being down.

The event's `payment_status` is derived from it. For `Authorised` it is `Authorised` or `Failed` depending on
`success`. For other events it is the event code. `query` remains the authoritative source of payment state.

## Django

```python
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from presto_pay import NotifyAck

from .models import PrestoWebhookEvent  # event_ref_num = models.CharField(max_length=64, unique=True)
from .payments import presto, fulfil


@csrf_exempt
@require_POST
def presto_notify(request):
    try:
        event = presto.webhooks.verify(request.body)
        try:
            with transaction.atomic():
                PrestoWebhookEvent.objects.create(event_ref_num=event.event_ref_num)
                fulfil(event)
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
from presto_pay import NotifyAck
from sqlalchemy.exc import IntegrityError

app = Flask(__name__)


@app.post("/presto/notify")
def presto_notify():
    try:
        event = presto.webhooks.verify(request.get_data())
        try:
            db.session.add(WebhookEvent(event_ref_num=event.event_ref_num))  # unique column
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
        else:
            fulfil(event)
            db.session.commit()
        body = NotifyAck.OK
    except Exception as exc:
        body = NotifyAck.for_error(exc)
    return body, 200, {"Content-Type": NotifyAck.CONTENT_TYPE}
```

## FastAPI

```python
import asyncpg
from fastapi import FastAPI, Request, Response
from presto_pay import AsyncPrestoPay, NotifyAck

app = FastAPI()
presto: AsyncPrestoPay = ...
pool: asyncpg.Pool = ...


@app.post("/presto/notify")
async def presto_notify(request: Request) -> Response:
    try:
        event = presto.webhooks.verify(await request.body())
        async with pool.acquire() as connection, connection.transaction():
            inserted = await connection.fetchval(
                "INSERT INTO presto_webhook_events (event_ref_num) VALUES ($1) "
                "ON CONFLICT DO NOTHING RETURNING event_ref_num",
                event.event_ref_num,
            )
            if inserted is not None:
                await fulfil(connection, event)
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
