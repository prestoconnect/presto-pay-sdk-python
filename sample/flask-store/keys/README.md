# Staging signing keys

Put the files from your Presto onboarding pack here. They are gitignored.

| File | Purpose |
|------|---------|
| `presto_rm_keystore.p12` | Merchant private key for request signing (PKCS#12, read directly — no conversion) |
| `presto_ext_service_dev.der` | Presto staging certificate for response and webhook verification |

Keys stored elsewhere can be pointed at with `PRESTOPAY_PRIVATE_KEY_FILE` and `PRESTOPAY_PUBLIC_KEY_FILE`
instead. Set the keystore password with `PRESTOPAY_PRIVATE_KEY_PASSWORD`.
