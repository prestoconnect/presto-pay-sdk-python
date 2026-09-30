# Changelog

## Unreleased

- Initial Python 3.11+ SDK: `init`, `query`, `reverse` and `refund`, sync (`PrestoPay`) and async
  (`AsyncPrestoPay`) over one sans-IO core, with a CI test that both send byte-identical requests.
- Request signing and response verification (RSASSA-PKCS1-v1_5 / SHA-256). Every vector in the vendored
  `presto-pay-spec` passes, including two staging captures verified against Presto's staging certificate.
- Keys from PKCS#8 PEM or DER, encrypted PEM, and PKCS#12 keystores, including the RC2-40 legacy encryption of
  the onboarding keystore. Presto keys from X.509 certificates (PEM or DER) or SPKI PEM, with several keys
  accepted at once for rotation.
- `may_have_taken_effect` and `reconcile_by` on every error, decided per operation where the error is raised.
- A whole-call `deadline` and a `retry_reads` policy (exponential backoff, full jitter, `Retry-After`).
  `init`, `reverse` and `refund` are retried only when `httpx` proves the request was never sent. A loopback
  socket suite proves that classification.
- Webhook verification with multi-`mid` and multi-key support and a 15-minute freshness window.
  `NotifyAck.for_error` answers permanent failures with `resend:false`.
- `sample/`: the MyStore checkout from the Java SDK's sample, as a Flask app on `PrestoPay` and a FastAPI app on
  `AsyncPrestoPay` sharing one set of templates and the same `checkout.js`.
- `from_env`, `strict` mode, redaction of card and receipt details from error bodies, and the `raw.post`
  escape hatch.
