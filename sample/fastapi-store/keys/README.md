# Staging signing keys

Put your staging key files here. They are gitignored.

| File | Where it comes from | Purpose |
|------|---------------------|---------|
| `presto_rm_keystore.p12` | The staging key pair you generated and registered with Presto; see [Create your key pair](../../../README.md#1-create-your-key-pair). A PEM key works too | Request signing (a `.p12` is read directly, no conversion) |
| `presto_ext_service_dev.der` | Presto | Presto's staging certificate, for response and webhook verification |

Keys stored elsewhere can be pointed at with `PRESTOPAY_PRIVATE_KEY_FILE` and `PRESTOPAY_PUBLIC_KEY_FILE`
instead. Set the keystore password with `PRESTOPAY_PRIVATE_KEY_PASSWORD`.
