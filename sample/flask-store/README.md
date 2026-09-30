# MyStore on Flask

The MyStore checkout on Flask, using the sync `PrestoPay` client. For the UI, the `POST /checkout` contract and
the webhook behaviour, see [the samples overview](../README.md).

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
over `.env`. The client is built with `PrestoPay.from_env()`.

## Run

Requires **Python 3.11+** and [uv](https://docs.astral.sh/uv/). The project installs the SDK from this
checkout.

```bash
cd sample/flask-store
uv sync
cp .env.example .env    # then fill in your staging credentials; add the key files under keys/
export APP_PUBLIC_BASE_URL=https://your-tunnel.example   # for webhooks and the redirect back
uv run flask --app mystore.app run --port 8080
```

Open [http://localhost:8080](http://localhost:8080). Run the tests with `uv run pytest`.

## Source layout

```
mystore/
├── app.py            create_app(): Flask routes over the sync PrestoPay client
├── checkout.py       Form validation, ringgit → sen, init arguments, gateway-error bodies, return-page data
├── config.py         .env / environment settings, startup logging
├── store.py          In-memory recent checkouts and webhooks (deduplicated on event_ref_num)
├── views.py          Jinja2 rendering
├── templates/        index.html, return.html, _webhooks.html
└── static/js/        checkout.js, served at /js/checkout.js
tests/                The routes against a mock gateway that signs its responses
```
