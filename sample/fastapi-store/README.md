# MyStore on FastAPI

The MyStore checkout on FastAPI, using the async `AsyncPrestoPay` client. For the UI, the `POST /checkout`
contract and the webhook behaviour, see [the samples overview](../README.md).

## Staging credentials

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
over `.env`. Settings are loaded and the client is built with `AsyncPrestoPay.from_env()` when the app starts.
The app's lifespan closes the client on shutdown.

## Run

Requires **Python 3.11+** and [uv](https://docs.astral.sh/uv/). `uv sync` installs this project and the SDK from
this checkout.

```bash
cd sample/fastapi-store
uv sync
cp .env.example .env    # then fill in your staging credentials; add the key files under keys/
export APP_PUBLIC_BASE_URL=https://your-tunnel.example   # for webhooks and the redirect back
uv run uvicorn fastapi_store.main:app --port 8080
```

Open [http://localhost:8080](http://localhost:8080). Run the tests with `uv run pytest`.

## Project layout

```
fastapi-store/
├── pyproject.toml
├── .env.example
├── keys/                      onboarding key files (gitignored)
├── src/fastapi_store/
│   ├── main.py                app: routers, static files, and the lifespan that builds the client
│   ├── config.py              Settings from .env and the environment, startup logging
│   ├── dependencies.py        Depends() providers for the settings, AsyncPrestoPay client and store
│   ├── schemas.py             CheckoutRequest (Pydantic), and the 400 {field: message} error handler
│   ├── services.py            the Presto calls: start a checkout, query a payment, accept a webhook
│   ├── store.py               in-memory recent checkouts and webhooks
│   ├── rendering.py           Jinja2Templates
│   ├── routers/
│   │   ├── checkout.py        GET /, POST /checkout
│   │   ├── payments.py        GET /return/{txn_ref_num}
│   │   └── webhooks.py        POST /presto/notify
│   ├── templates/             index.html, return.html, partials/
│   └── static/js/checkout.js  the checkout page's script
└── tests/                     routes and the request schema, against a mock gateway that signs its responses
```

FastAPI rejects invalid input with a 422 and a list of errors by default. `schemas.validation_failed` turns that
into a 400 with a `{field: message}` map instead, because the checkout page's script expects that shape.
