# Payments and errors

This guide covers the four payment operations and how to handle their failures. It assumes you've set up a
client as in the [quick start](../README.md#quick-start).

- [Making requests](#making-requests)
- [Results](#results)
- [Reverse or refund](#reverse-or-refund)
- [Errors](#errors)
- [When you don't know whether it worked](#when-you-dont-know-whether-it-worked)
- [Retries and deadlines](#retries-and-deadlines)

## Making requests

`presto.payments` has four operations: `init`, `query`, `reverse` and `refund`. Each one takes keyword arguments
named after the gateway's wire fields in snake_case, so `txnRefNum` becomes `txn_ref_num`. Amounts are `int`
minor currency units (`10_000` is MYR 100.00). A `float` or `Decimal` is rejected, because `1200.0` would sign as
a different string than `1200`. Unset optional fields are left out of the request, never sent as `null`.

```python
from presto_pay import LineItem, PaymentMethod, TxnType

payment = presto.payments.init(
    presto_mrn=presto_mrn,
    txn_type=TxnType.WEB_PAY,
    txn_ref_num="order-123",
    display_desc="Order 123",
    amount=10_000,
    currency_code="MYR",
    redirect_url="https://shop.example/return/order-123",
    notify_url="https://shop.example/presto/notify",
    allowed_payment_methods=[PaymentMethod.WALLET, PaymentMethod.CARD],  # only for your own selection page
    item_list=[LineItem(item_desc="Tea", quantity=2, unit_amount=500, total_amount=1_000)],
    session_validity=datetime.now(UTC) + timedelta(minutes=15),
)

current = presto.payments.query(presto_mrn=presto_mrn, txn_ref_num="order-123")

presto.payments.reverse(
    presto_mrn=presto_mrn,
    payment_ref_num=current.payment_ref_num,
    reversal_ref_num="order-123-reversal",
    remark="Customer cancelled",
)

presto.payments.refund(
    presto_mrn=presto_mrn,
    payment_ref_num=current.payment_ref_num,
    refund_ref_num="order-123-refund-1",
    remark="Customer request",
    amount=2_500,  # omit for a full refund
)
```

`init` validates its input before sending anything:

- `qr_value` and `payer_ref_num` are mutually exclusive.
- `currency_code` is required when `amount` is set.
- `redirect_url` is required for `TxnType.WEB_PAY`.

`query` needs `payment_ref_num` or `txn_ref_num`, and so does `reverse`. A validation failure raises
`PrestoPayConfigError`, whose `field` names the argument.

Documented field lengths, such as 50 characters for `txn_ref_num`, are not enforced by default because the
gateway doesn't enforce them either. `strict=True` enforces them.

## Results

Each operation returns a frozen dataclass: `InitResult`, `QueryResult`, `ReverseResult` or `RefundResult`.

- **Empty values.** An optional field that the gateway sends empty, as either `""` or `null`, is `None`. The
  gateway uses the two interchangeably.
- **List fields.** `payment_details` and `refund_details` are tuples of `PaymentDetail` / `RefundDetail`. On the
  wire they are JSON strings.
- **Dates.** Date fields stay strings. `parse_gateway_timestamp()` turns them into aware `datetime`s at
  UTC+08:00.
- **Raw body.** `result.raw` holds the full wire body, including fields the SDK doesn't model yet.

Status and method fields are plain `str`. Compare them against the constants:

```python
if current.payment_status == PaymentStatus.AUTHORISED:
    ...
current.reversal_status  # Reversing, Failed or Success, once you've requested a reversal
current.refund_status  # Refunding, Failed or Success, once you've requested a refund
PaymentMethod.try_parse(detail.method)  # None for a method this SDK version doesn't know
```

## Reverse or refund

`reverse` undoes a whole payment. What happens depends on the payment's status:

- **`PendingAuthorise`** (not paid yet): the payment is cancelled and its status becomes `Cancelled`.
- **`Expired`**: fails with `1219` (`ErrorCode.INVALID_STATUS_FOR_REVERSAL`). There's nothing left to undo.
- **Paid**: the gateway decides. It can refuse once the payment has settled (`1220`) or its reversal window has
  passed (`1221`). Use `refund` instead in that case.

`refund` returns all or part of a paid payment's amount. On an unpaid (`PendingAuthorise`) payment it fails with
`1227`; use `reverse` to cancel it instead. A refund can be requested for any payment method, and the gateway
decides the outcome. Some methods are settled manually or offline, so an accepted refund request doesn't mean
the refund is complete. Check `refund_status` with `query`, or wait for the `Refunded` webhook, before treating
it as final.

## Errors

Every error is a `PrestoPayError` and carries `operation`, `may_have_taken_effect` and `reconcile_by`.

| Class | When | Extra attributes |
|-------|------|------------------|
| `PrestoPayConfigError` | Invalid options or request input, including bad keys and unencodable strings | `field` |
| `PrestoPayTransportError` | Network failure or timeout | `request_not_sent` |
| `PrestoPayApiError` | Non-200 status (`kind="http"`) or `success: false` (`kind="business"`) | `http_status`, `error_code`, `error_message`, `raw_body`; `canonical` on `1006`/`1007`; `clock_offset` on `1005` |
| `PrestoPaySignatureError` | Missing or invalid signature, wrong webhook `mid`, stale webhook `ts` | `source`, `canonical` |
| `PrestoPayResponseError` | Malformed body, missing required field, bad `ts`, echo mismatch | `source`, `raw_body` |

Compare error codes against `ErrorCode`, for example `exc.error_code == ErrorCode.PAYMENT_NOT_FOUND`. Unknown codes
pass through as strings. The original `httpx` exception is chained as `__cause__`; no `httpx` type is part of
the public API. Three codes add extra context:

- **`1005`**: the request `ts` is outside the gateway's 15-minute window. `clock_offset` holds the difference
  in seconds between the gateway clock and yours. Fix the host clock (NTP). All timestamps use a fixed UTC+08:00
  offset, whatever the host's time zone.
- **`1006` / `1007`**: the gateway couldn't verify the request signature. `canonical` holds the string the SDK
  signed. Check that the private key matches the public key you registered with Presto.
- **`1203`**: see below.

**Redaction.** `raw_body` and `canonical` can contain card, receipt and customer details. By default the
values of `cardBin`, `cardSummary`, `receiptEmail`, `receiptName`, `qrValue`, `payerRefNum`, `bindData`,
`deviceIp`, `deviceRefNum` and `transactionalData` are replaced with `[redacted]`, including inside the
stringified `paymentDetails`. An unparseable body is replaced entirely. `str()` and `repr()` of an error never
include a body. To keep full bodies while debugging, pass `redact_error_bodies=False`.

**Strict mode.** `strict=True` rejects contract drift that is tolerated by default: a number where the gateway
documents a string, or a field longer than its documented maximum. Use it in staging.

## When you don't know whether it worked

For `init`, `reverse` and `refund`, these failures leave the outcome unknown:

- a transport failure after the request may have been sent;
- an HTTP 5xx;
- a response that fails parsing, signature verification, field mapping or the echo check.

These errors have `may_have_taken_effect=True`, and a `reconcile_by` key you can pass straight to `query`.
`may_have_succeeded(exc)` checks the same thing when you've caught `Exception`.

**`init`: call it again with the same `txn_ref_num`.** That's safe. If the first call reached Presto, you get the
existing payment and its current status back rather than a second payment:

```python
from presto_pay import PrestoPayError

try:
    payment = presto.payments.init(**request)
except PrestoPayError as exc:
    if not exc.may_have_taken_effect:
        raise
    payment = presto.payments.init(**request)  # same txn_ref_num: returns the payment if it was created
```

`1203` on `init` proves a record with that `txn_ref_num` exists but not its state, so it is also flagged
`may_have_taken_effect`; `query` it to find the state.

**`reverse` and `refund`: check before trying again.** Sending one of these twice could reverse or refund twice,
so query first, and look at `reversal_status` or `refund_status`. Try again only if the first request didn't
take effect:

```python
try:
    presto.payments.refund(...)
except PrestoPayError as exc:
    if not exc.may_have_taken_effect or exc.reconcile_by is None:
        raise
    current = presto.payments.query(**exc.reconcile_by)
```

`reconcile_by` holds `presto_mrn` plus `txn_ref_num` after `init`, or `payment_ref_num` after `reverse` and
`refund`. It is `None` for `presto.raw.post`, which can't know the lookup key for an endpoint the SDK doesn't
model. The same failures on `query` mean nothing happened, and the SDK retries them automatically.

## Retries and deadlines

The SDK **never** automatically resends `init`, `reverse` or `refund` once any byte of the request may have
reached the gateway. It retries them only when `httpx` shows the request was never sent (DNS failure, refused or
timed-out connect, TLS failure, pool timeout). `query` is read-only, so it is also retried on other transport
errors and on HTTP 5xx.

Retries use exponential backoff with full jitter and honour `Retry-After`. All attempts, backoff included, share
one whole-call `deadline` (30 s by default). Configure them with
`retry_reads=RetryReads(max_retries=2, initial_backoff=0.2, max_backoff=5.0)`.

`AsyncPrestoPay` enforces the deadline exactly. `PrestoPay` limits each connect, write and read to the time
remaining, and checks the deadline after each chunk of the response. A single network operation that stalls can
still run up to its own limit before the deadline is noticed.
