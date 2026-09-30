# Samples

## MyStore

**MyStore** is a checkout page that runs against **Presto staging**, ported from the Java SDK's sample with
the same UI and behaviour. It is styled with Tailwind CSS (Play CDN) and Font Awesome icons, and jQuery drives
the page's JSON checkout calls. It ships as two apps that share everything except the web framework:

| App | Framework | SDK client | Run |
|-----|-----------|------------|-----|
| [`mystore/flask_app.py`](mystore/flask_app.py) | Flask | `PrestoPay` (sync) | `uv run flask --app mystore.flask_app run --port 8080` |
| [`mystore/fastapi_app.py`](mystore/fastapi_app.py) | FastAPI | `AsyncPrestoPay` (async) | `uv run uvicorn mystore.fastapi_app:create_app --factory --port 8080` |

### Staging credentials

Use the staging merchant credentials from your Presto onboarding pack. No secrets ship with the sample.

1. Copy the `.p12` and `.der` files into [`keys/`](keys/). See [`keys/README.md`](keys/README.md). They are
   gitignored.
2. Copy [`.env.example`](.env.example) to `.env` (also gitignored) and fill in your MID, Presto MRN and keystore
   password.

| Setting | Default |
|---------|---------|
| Environment | `staging` |
| Private key | `keys/presto_rm_keystore.p12` |
| Presto public key | `keys/presto_ext_service_dev.der` |

Any value can also come from an exported `PRESTOPAY_*` / `APP_*` environment variable, which takes precedence
over `.env`. The client itself is built with `PrestoPay.from_env()` / `AsyncPrestoPay.from_env()`.

### Checkout UI

There is one page ([`/`](http://localhost:8080/)). It has a **"Show payment methods on checkout"** toggle that
switches between the two ways to call `init`. Either way, the page's JavaScript sends the order as JSON to
`POST /checkout`; it is not a browser form post.

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

### Source layout

```
mystore/
├── flask_app.py      Flask routes over the sync PrestoPay client
├── fastapi_app.py    FastAPI routes over the async AsyncPrestoPay client
├── checkout.py       Form validation, ringgit → sen, init arguments, gateway-error bodies, return-page data
├── config.py         .env / environment settings, startup logging
├── store.py          In-memory recent checkouts and webhooks (deduplicated on event_ref_num)
├── views.py          Jinja2 rendering shared by both apps
├── templates/        index.html, return.html, _webhooks.html
└── static/js/        checkout.js — the Java sample's script, unchanged
tests/                Every scenario runs against both apps, with a mock gateway that signs its responses
```

### Requirements

- **Python 3.11+** and [uv](https://docs.astral.sh/uv/). The sample installs the SDK from this checkout.

### Run

```bash
cd sample
uv sync
cp .env.example .env    # then fill in your staging credentials; add the key files under keys/
export APP_PUBLIC_BASE_URL=https://your-tunnel.example   # for webhooks and the redirect back
uv run flask --app mystore.flask_app run --port 8080
# or: uv run uvicorn mystore.fastapi_app:create_app --factory --port 8080
```

Open [http://localhost:8080](http://localhost:8080). Run the tests with `uv run pytest`.

### Webhooks (`notify_url`)

Each payment `init` sends `notify_url` = `{APP_PUBLIC_BASE_URL}/presto/notify`. Presto's servers POST events to
that URL from **outside your network**. If the URL is not publicly reachable (for example
`http://localhost:8080/...`), **webhooks will not arrive**. Payments can still complete, but this demo's
"Recent webhooks" list and anything else driven by notify will stay empty.

Use a tunnel (for example `ngrok http 8080`) or a deployed host, and set `APP_PUBLIC_BASE_URL` to that origin
(HTTPS recommended). The payer's `redirect_url` uses the same base, so return links work in the browser too.

Each `init` sets `redirect_url` to `{base}/return/{txnRefNum}`. The `/return/{txnRefNum}` handler **requires**
that path segment. A bare `/return` shows an explanatory page instead.

`/presto/notify` behaves differently from the Java sample in two ways. Both follow the Python SDK's webhook
guidance:

- **Deduplication.** It deduplicates on `event_ref_num`. Presto redelivers an event up to four more times, and
  each redelivery is still acknowledged but listed only once.
- **Rejected webhooks.** It answers a webhook it rejects (bad signature, foreign `mid`, stale `ts`) with HTTP
  200 and `NotifyAck.for_error(exc)` (`{"resend":false}`) rather than 401 or 400. A permanent failure never
  asks Presto to resend.
