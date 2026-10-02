# Staging signing keys

Put your staging key files here. They are gitignored.

| File | Where it comes from | Purpose |
|------|---------------------|---------|
| `merchant-key.pem` | The PEM private key of the staging key pair you generated and registered with Presto; see [Create your key pair](../../../README.md#1-create-your-key-pair) | Request signing |
| `presto.der` | Presto | Presto's staging certificate, for response and webhook verification |

The sample has no default key paths: set `PRESTOPAY_PRIVATE_KEY_FILE` and `PRESTOPAY_PUBLIC_KEY_FILE` in `.env`.
The files can live anywhere as long as those settings point at them. Set `PRESTOPAY_PRIVATE_KEY_PASSWORD` only
if your PEM key is encrypted.
