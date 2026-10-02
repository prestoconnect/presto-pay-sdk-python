# Changelog

## Unreleased

- Webhook guidance now guards on the order record instead of deduplicating on `event_ref_num`: the handler
  queries the payment on every delivery and applies its status with a conditional update that finalises an
  order only once and fulfils only on the change into `Authorised`. Updated the README, `docs/webhooks.md`
  (including the Django, Flask and FastAPI handlers), `docs/production.md`, the wire contract, the
  `max_timestamp_age` error message, and the Flask and FastAPI samples, whose return page and webhook now share
  one guarded update.
- New `docs/payment-methods.md`, linked from the README: every payment method code with its SDK constant,
  a note that Presto enables payment methods per merchant during onboarding, which methods need a Presto
  account (the PrestoPay eWallet and Credits, `Card` and the loyalty programmes), which are legacy
  (`TouchNGo`, `BigLife`), and how to pass a code the SDK doesn't list yet.
- The Flask and FastAPI samples take a PEM merchant private key and no longer default the environment or the
  key paths: set `PRESTOPAY_ENV`, `PRESTOPAY_PRIVATE_KEY_FILE` and `PRESTOPAY_PUBLIC_KEY_FILE` in `.env`.

## 0.1.2 - 2026-10-01

Documentation only; no change to the SDK's behaviour.

- The README's key-pair command makes the merchant certificate valid for 99999 days, so it doesn't expire and
  need registering with Presto again.
- The README's `init` example uses `PaymentMethod.PM_PG_CARD` as the card method for a merchant's own payment
  selection page.

## 0.1.1 - 2026-10-01

- The README is now a getting-started guide: creating your key pair and sending Presto the `.der` public key,
  how a payment flows, a four-step quick start and a payment status table. Reference material moved into
  `docs/`. The Django, Flask and FastAPI webhook handlers in `docs/webhooks.md` now query the payment and
  answer HTTP 401 to a `PrestoPaySignatureError`, and `docs/production.md` shows how to convert Presto's `.der`
  certificate to PEM for an inline `PRESTOPAY_PUBLIC_KEY`.
- The Flask and FastAPI samples answer HTTP 401 to a webhook that fails with a `PrestoPaySignatureError`,
  instead of acknowledging it.

## 0.1.0 - 2026-10-01

First published release.

- Initial Python 3.11+ SDK: `init`, `query`, `reverse` and `refund`, sync (`PrestoPay`) and async
  (`AsyncPrestoPay`) over one sans-IO core, with a CI test that both send byte-identical requests.
- Request signing and response verification (RSASSA-PKCS1-v1_5 / SHA-256). Every vector in the vendored
  `presto-pay-spec` passes, including two staging captures verified against Presto's staging certificate.
- Keys from PKCS#8 PEM or DER, encrypted PEM, and PKCS#12 keystores, including the RC2-40 legacy encryption of
  the onboarding keystore. Presto keys from X.509 certificates (PEM or DER) or SPKI PEM, with several keys
  accepted at once for rotation.
- `may_have_taken_effect` and `reconcile_by` on every error, decided per operation where the error is raised.
- A whole-call `deadline` and a `retry_reads` policy (exponential backoff, full jitter, `Retry-After`). The async
  client enforces the deadline exactly, and the sync client checks it after each chunk of the response. `init`,
  `reverse` and `refund` are retried only when `httpx` proves the request was never sent. A loopback socket suite
  proves that classification.
- Webhook verification with multi-`mid` and multi-key support and a 15-minute freshness window.
  `NotifyAck.for_error` answers `resend:false` only when verifying the webhook itself failed. Errors from calls
  made inside the handler get `resend:true`, so the event is redelivered. `WebhookEvent` carries `event_code` and
  `success` as sent and derives no payment status; handlers call `query` for the latest status.
- `sample/flask-store/` and `sample/fastapi-store/`: a MyStore checkout sample, on Flask with `PrestoPay` and on
  FastAPI with `AsyncPrestoPay`.
- `from_env`, `strict` mode, and the `raw.post` escape hatch.
- Error bodies and canonical strings are redacted of card, receipt and customer details (`qrValue`,
  `payerRefNum`, `bindData`, device and transactional data).
- Constructors reject a mismatched `http_client` (sync versus async), and non-finite `deadline`, backoff and
  webhook-window values.
