# Samples

## MyStore

**MyStore** is a checkout page that runs against **Presto staging**. It is styled with Tailwind CSS (Play CDN)
and Font Awesome icons, and jQuery drives the page's JSON checkout calls. It is built twice, as two
self-contained projects. Copy whichever one matches your stack:

| Folder | Framework | SDK client | Run (from the folder) |
|--------|-----------|------------|-----------------------|
| [`flask-store/`](flask-store/) | Flask | `PrestoPay` (sync) | `uv run flask --app flask_store run --port 8080` |
| [`fastapi-store/`](fastapi-store/) | FastAPI | `AsyncPrestoPay` (async) | `uv run uvicorn fastapi_store.main:app --port 8080` |

Each project is an installable package under `src/`, organised the way its framework expects:

- **Flask:** an application factory, Blueprints and `render_template`.
- **FastAPI:** a Pydantic request model, `APIRouter`s, `Depends()` and `Jinja2Templates`.

Both keep the Presto calls in `services.py`, apart from the routes. The two versions differ only in `async` and
`await`. The page itself is the same in both: the same templates and the same `checkout.js`. Each folder's
README covers credentials, how to run it and its project layout.

### Checkout UI

There is one page ([`/`](http://localhost:8080/)). It has a **"Show payment methods on checkout"** toggle that
switches between the two ways to call `init`. Either way, the page sends the order as JSON to `POST /checkout`;
it is not a browser form post.

| Toggle | Experience | SDK |
|--------|------------|-----|
| Off (default) | Amount + description → Presto hosted page | `init` without `allowed_payment_methods` |
| On | Payment method list shown on this page first | `init` with `allowed_payment_methods=[...]` and the optional receipt fields |

`POST /checkout` accepts a JSON body and returns one of:

- `200` with `{"paymentUrl": "...", "txnRefNum": "..."}` on success. The page then redirects the browser to
  `paymentUrl`, or to `/return/{txnRefNum}` if Presto returned none.
- `400` with a map of field name to message when validation fails, for example `{"amountInRinggit": "Amount
  must be at least 0.01"}`.
- `502` with `{"message": "...", "mayHaveTakenEffect": false, ...}` on a gateway failure (signature, transport or
  API error). API errors add `errorCode` and `errorMessage`, and signature failures add `signatureError`.

`GET /return/{txnRefNum}` shows the payment result, using `payments.query()` for the authoritative status.

### Webhooks (`notify_url`)

Each payment `init` sends `notify_url` = `{APP_PUBLIC_BASE_URL}/presto/notify`. Presto's servers POST events to
that URL from **outside your network**. If the URL is not publicly reachable (for example
`http://localhost:8080/...`), **webhooks will not arrive**. Payments can still complete, but this demo's
"Recent webhooks" list and anything else driven by notify will stay empty.

Use a tunnel (for example `ngrok http 8080`) or a deployed host, and set `APP_PUBLIC_BASE_URL` to that origin
(HTTPS recommended). The payer's `redirect_url` uses the same base, so return links work in the browser too.

Each `init` sets `redirect_url` to `{base}/return/{txnRefNum}`. The `/return/{txnRefNum}` handler **requires**
that path segment. A bare `/return` shows an explanatory page instead.

`/presto/notify` follows the SDK's webhook guidance:

- **Status from `query`.** After verifying an event, it queries the payment by `payment_ref_num`, and the
  "Recent webhooks" list shows the status that `query` returned. If the query fails, it answers
  `{"resend":true}` without recording the event, so Presto's redelivery tries again.
- **Deduplication.** It deduplicates on `event_ref_num`. Presto redelivers an event up to four more times, and
  each redelivery is still acknowledged but listed only once.
- **Rejected webhooks.** It answers a webhook it rejects (bad signature, foreign `mid`, stale `ts`) with HTTP
  200 and `NotifyAck.for_error(exc)` (`{"resend":false}`). A permanent failure never asks Presto to resend.
