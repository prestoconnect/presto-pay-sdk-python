# Production

- [Configuration from environment](#configuration-from-environment)
- [Keys](#keys)
- [Several merchants](#several-merchants)
- [Clients, deadlines and logging](#clients-deadlines-and-logging)
- [Custom HTTP client](#custom-http-client)
- [Going live checklist](#going-live-checklist)
- [Troubleshooting](#troubleshooting)

## Configuration from environment

```python
import os

from presto_pay import PrestoPay

presto = PrestoPay.from_env(os.environ)
```

`from_env` accepts any mapping: `os.environ`, a dict from a secrets manager, or flattened Django settings. It
also takes the constructor's other options as keyword arguments, such as `http_client`, `deadline` and `strict`.
`AsyncPrestoPay.from_env` works the same way.

| Variable | Value |
|----------|-------|
| `PRESTOPAY_ENV` or `PRESTOPAY_BASE_URL` | `staging` / `production`, or an explicit HTTPS base URL (set one, not both) |
| `PRESTOPAY_MID` | Your `mid` |
| `PRESTOPAY_PRIVATE_KEY` or `PRESTOPAY_PRIVATE_KEY_FILE` | PEM text, or a path to a PEM, DER or `.p12` file |
| `PRESTOPAY_PRIVATE_KEY_PASSWORD` | The keystore or encrypted-PEM password, if any |
| `PRESTOPAY_PUBLIC_KEY` or `PRESTOPAY_PUBLIC_KEY_FILE` | Presto's certificate as PEM text, or a path to its `.der` file |

If a PEM is stored on one line with literal `\n` sequences (common in `.env` files and secrets managers), it is
unescaped automatically.

`PRESTOPAY_PUBLIC_KEY` holds text, so it can't hold the binary `.der` file. Either point
`PRESTOPAY_PUBLIC_KEY_FILE` at the `.der`, or convert it to PEM once and use the contents of `presto.pem`:

```bash
openssl x509 -inform der -in presto.der -out presto.pem
```

## Keys

`private_key` takes a `Path` to, or the bytes of, a PKCS#8 PEM, an encrypted PEM, a DER key or a `.p12`
keystore; pass `private_key_password` when it has one. The SDK reads `.p12` keystores directly, including the
RC2-40 encryption some keystores use, which the OpenSSL 3 command line rejects without its legacy provider. You
don't need to convert one.

Keep the private key, or `.p12` keystore, and its password in your secret store, outside the repository and the
web root, with restricted file permissions.

`presto_public_key` takes Presto's certificate as a `Path`, DER bytes or PEM text. A `str` is always treated
as PEM, so pass a `Path` for a file. Presto announces key rotations out of band, and there is no key ID on the
wire, so during the overlap pass both certificates, for example `presto_public_key=[old, new]`, and the SDK
tries each in turn.

## Several merchants

Each client belongs to one merchant: `merchant_id` goes on the constructor and is sent with every request, and
the client's webhook verifier rejects events for any other `mid`. `presto_mrn` is passed on each call, because
one `mid` can have several.

To serve several merchants, create one client per `mid`. They can share keys and an `httpx` client. To receive
webhooks for several merchants on one endpoint, use `create_webhook_verifier(merchant_id={...})`; see
[Webhooks](webhooks.md#verify-the-raw-body).

## Clients, deadlines and logging

**Clients and pools.** Create one client per process and reuse it. An injected `httpx.Client` is never closed by
the SDK, so it is safe to share across Celery tasks or Django requests. Build the client after forking, not
before.

**Deadlines.** `deadline` (30 s by default) covers the whole call, including retries and backoff. Set it below
the request budget of your web server or task runner so the SDK's exception reaches your code before the process
is killed mid-retry. `AsyncPrestoPay` enforces the deadline exactly, respects an outer `asyncio.timeout()`, and
never turns cancellation into an SDK error. `PrestoPay` checks the deadline after each chunk of the response,
and limits each connect, write and read to the time remaining, so leave some headroom.

**Logging.** Error bodies and canonical strings have card, receipt and customer details redacted by default.
Keep `redact_error_bodies=True` in production. Result dataclasses leave `raw` and card fields out of their
`repr`, but `dataclasses.asdict(result)` includes them.

## Custom HTTP client

Pass your own `httpx.Client` (or `httpx.AsyncClient`) to set up proxies, TLS, connection limits or tracing, or to
share a pool:

```python
import httpx

presto = PrestoPay(..., http_client=httpx.Client(proxy="http://proxy.internal:3128"))
```

The SDK sets the timeout on each request and turns redirects off. It never closes a client you pass in; it
closes only the one it creates, when you use `with` / `async with`, `close()` or `aclose()`. Don't configure the
client to retry requests. `httpx.HTTPTransport(retries=n)` is safe because it retries only failed connections,
which never send any bytes.

## Going live checklist

- [ ] Generate a separate key pair for production and register its public key with Presto.
- [ ] Use `environment="production"` with your production `mid`, `prestoMrn` and Presto certificate. Never mix
      staging and production values.
- [ ] Load the private key and its password from a secret store, not from source control or the image.
- [ ] Make `notify_url` a public HTTPS URL that Presto can reach.
- [ ] Have your return page `query` the payment instead of trusting the redirect.
- [ ] Have your webhook handler verify the raw body, `query` the payment, apply its status with a guarded update that
      finalises an order only once and fulfils only on the change into `Authorised`, return 401 for a `PrestoPaySignatureError`, and reply `NotifyAck.RESEND` when your own
      processing fails.
- [ ] Store `txn_ref_num`, `payment_ref_num` and the order's payment status. After a timeout or server error,
      call `init` again with the same `txn_ref_num`, and query before retrying `reverse` or `refund`, as in
      [Payments and errors](payments-and-errors.md#when-you-dont-know-whether-it-worked).
- [ ] Keep the host clock in sync with NTP.
- [ ] Log `error_code` and `error_message` from `PrestoPayApiError`, so you can quote them to Presto support.
- [ ] In staging, run with `strict=True` and the opt-in smoke test (`PRESTOPAY_STAGING_SMOKE=1 pytest -m staging`),
      which exercises the payment lifecycle against real staging.

## Troubleshooting

**`1005` (`ErrorCode.CLOCK_SKEW`).** Your request's timestamp is more than 15 minutes from Presto's clock.
`PrestoPayApiError.clock_offset` reports the gap the SDK observed. Sync the host clock with NTP; the SDK uses a
fixed UTC+08:00 offset whatever the host's time zone.

**`1006` or `1007` (`ErrorCode.INVALID_SIGNATURE`, `ErrorCode.SIGNATURE_VERIFICATION_FAILED`).** Presto couldn't
verify your signature. Usually the private key doesn't match the public key you registered for this
environment, or you're using a staging key in production or the other way round. `exc.canonical` holds the
exact string the SDK signed, and `canonicalize(body)` rebuilds it from a raw JSON body.

**`PrestoPaySignatureError` from a payment call.** Presto's response didn't verify with the certificate you
configured. Check that it's the certificate for this environment, and whether Presto has announced a new one.

**`1102` or `1106` (`ErrorCode.INVALID_MID`, `ErrorCode.INVALID_MERCHANT_REFERENCE`).** The `mid` or
`prestoMrn` isn't valid for this environment.

**Webhooks never arrive.** `notify_url` must be reachable from the internet. `localhost` and private addresses
won't work; during development, use a tunnel such as ngrok and pass its URL as `notify_url`.

**Webhooks fail with `PrestoPaySignatureError`.** Either the event is for a `mid` the verifier wasn't given, its
timestamp is more than 15 minutes from your clock (sync with NTP), or the Presto certificate is for the wrong
environment.

**An endpoint the SDK doesn't cover.** `presto.raw.post(path, body)` signs, sends, verifies and returns the
parsed dict. `presto.raw.sign(canonical)` and `presto.raw.verify_body(body)` expose the two halves.
`parse_gateway_timestamp` reads the gateway's `yyyyMMddHHmmss.SSS` date fields into aware `datetime`s.
