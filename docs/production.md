# Production setup

**Credentials.** Use the production environment only with production merchant credentials. Keep the private
key or `.p12` keystore and its password in your secret store, outside the repository and the web root.
Restrict file permissions.

**Key rotation.** Presto announces key rotations to partners out of band. There is no key ID on the wire, so
during the overlap pass both certificates, for example `presto_public_key=[old, new]`, and the SDK tries each in
turn.

**Clock.** Keep the host clock accurate with NTP. Every request carries a timestamp at a fixed UTC+08:00 offset,
and the gateway rejects timestamps more than 15 minutes out with `1005`. When that happens,
`PrestoPayApiError.clock_offset` reports the gap the SDK observed.

**Deadlines.** `deadline` (30 s by default) covers the whole call, including retries and backoff. Set it below
the request budget of your web server or task runner so the SDK's exception reaches your code before the process
is killed mid-retry. `AsyncPrestoPay` also respects an outer `asyncio.timeout()`, and cancellation is never
turned into an SDK error.

**Clients and pools.** Create one client per process and reuse it. An injected `httpx.Client` is never closed by
the SDK, so it is safe to share across Celery tasks or Django requests. Build the client after forking, not
before.

**Persistence.** Store `txn_ref_num`, `payment_ref_num` and the webhook `event_ref_num`s. After any error with
`may_have_taken_effect`, query before deciding what to do. Never assume the payment failed. A refund request can
need manual or offline processing depending on the payment method, so an accepted refund request doesn't mean the
refund is complete.

**Logging.** Error bodies and canonical strings have card and receipt details redacted by default. Keep
`redact_error_bodies=True` in production. Result dataclasses leave `raw` and card fields out of their `repr`,
but `dataclasses.asdict(result)` includes them.

**Staging.** Run staging with `strict=True`, which rejects contract drift the production default tolerates. The
opt-in smoke test (`PRESTOPAY_STAGING_SMOKE=1 pytest -m staging`) exercises the payment lifecycle against real
staging. Never commit merchant credentials, onboarding keystores or captured customer data.
